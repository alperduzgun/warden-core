/**
 * IPC Client for communicating with Warden backend
 * Handles socket connection and message passing
 */

import {createConnection, Socket} from 'node:net';
import type {IPCResponse} from './types.js';
import {logger} from '../utils/logger.js';

const IPC_SOCKET_PATH = '/tmp/warden-ipc.sock';
const CONNECTION_TIMEOUT = 15000; // 15s for slower systems
const RESPONSE_TIMEOUT = 45000; // 45s for command responses (scan can take time)

export class IPCClient {
  private socket: Socket | null = null;
  private connected = false;

  /**
   * Connect to the IPC server
   */
  async connect(): Promise<boolean> {
    return new Promise((resolve, reject) => {
      logger.debug('ipc_connecting', {socket_path: IPC_SOCKET_PATH});

      const socket = createConnection(IPC_SOCKET_PATH);
      const timeout = setTimeout(() => {
        socket.destroy();
        logger.error('ipc_connection_timeout', {
          timeout_ms: CONNECTION_TIMEOUT,
          socket_path: IPC_SOCKET_PATH,
        });
        reject(new Error(`Connection timeout after ${CONNECTION_TIMEOUT}ms`));
      }, CONNECTION_TIMEOUT);

      socket.on('connect', () => {
        clearTimeout(timeout);
        this.socket = socket;
        this.connected = true;
        logger.info('ipc_connected', {socket_path: IPC_SOCKET_PATH});
        resolve(true);
      });

      socket.on('error', (error) => {
        clearTimeout(timeout);
        logger.error('ipc_connection_failed', {
          error: error.message,
          socket_path: IPC_SOCKET_PATH,
        });
        reject(error);
      });
    });
  }

  /**
   * Send a command to the IPC server (JSON-RPC 2.0)
   */
  async send<T>(command: string, params: Record<string, unknown> = {}): Promise<IPCResponse<T>> {
    if (!this.connected || !this.socket) {
      throw new Error('Not connected to IPC server');
    }

    return new Promise((resolve, reject) => {
      if (!this.socket) {
        reject(new Error('Socket not available'));
        return;
      }

      const requestId = Date.now();

      // JSON-RPC 2.0 format
      const message = JSON.stringify({
        jsonrpc: '2.0',
        id: requestId,
        method: command,
        params: params
      });

      logger.debug('ipc_send', {
        command,
        request_id: requestId,
        params_count: Object.keys(params).length,
      });

      let buffer = '';
      let responseReceived = false;

      // Response timeout
      const responseTimeout = setTimeout(() => {
        if (!responseReceived) {
          this.socket?.off('data', onData);
          this.socket?.off('error', onError);
          logger.error('ipc_response_timeout', {
            command,
            request_id: requestId,
            timeout_ms: RESPONSE_TIMEOUT,
            buffer_length: buffer.length,
          });
          reject(new Error(`Response timeout after ${RESPONSE_TIMEOUT}ms for command: ${command}`));
        }
      }, RESPONSE_TIMEOUT);

      const onData = (data: Buffer) => {
        buffer += data.toString();

        logger.debug('ipc_data_received', {
          chunk_length: data.length,
          buffer_length: buffer.length,
          has_newline: buffer.includes('\n'),
        });

        // Process all complete lines (JSON-RPC uses line-delimited JSON)
        while (buffer.includes('\n')) {
          const lineEnd = buffer.indexOf('\n');
          const line = buffer.substring(0, lineEnd).trim();
          buffer = buffer.substring(lineEnd + 1);

          if (line && !responseReceived) {
            responseReceived = true;
            clearTimeout(responseTimeout);

            try {
              const jsonRpcResponse = JSON.parse(line);
              this.socket?.off('data', onData);
              this.socket?.off('error', onError);

              logger.debug('ipc_response_parsed', {
                command,
                request_id: requestId,
                has_error: !!jsonRpcResponse.error,
                has_result: !!jsonRpcResponse.result,
              });

              // Convert JSON-RPC response to our IPCResponse format
              if (jsonRpcResponse.error) {
                logger.warning('ipc_command_error', {
                  command,
                  error: jsonRpcResponse.error.message,
                });
                resolve({
                  success: false,
                  error: jsonRpcResponse.error.message || 'Unknown error'
                });
                break; // Exit the while loop after processing error response
              } else {
                logger.debug('ipc_command_success', {command});
                resolve({
                  success: true,
                  data: jsonRpcResponse.result as T
                });
                break; // Exit the while loop after successfully processing the response
              }
            } catch (e) {
              logger.error('ipc_parse_error', {
                command,
                error: e instanceof Error ? e.message : 'Unknown',
                buffer_preview: buffer.substring(0, 100),
              });
              reject(new Error('Failed to parse response: ' + e));
            }
          }
        }
      };

      const onError = (error: Error) => {
        responseReceived = true;
        clearTimeout(responseTimeout);
        this.socket?.off('data', onData);
        this.socket?.off('error', onError);
        logger.error('ipc_socket_error', {
          command,
          error: error.message,
        });
        reject(error);
      };

      this.socket.on('data', onData);
      this.socket.once('error', onError);
      this.socket.write(message + '\n');
    });
  }

  /**
   * Disconnect from the IPC server
   */
  disconnect(): void {
    if (this.socket) {
      this.socket.destroy();
      this.socket = null;
      this.connected = false;
    }
  }

  /**
   * Send a streaming command to the IPC server
   * @param command Command to execute
   * @param params Command parameters
   * @param onData Callback for each data chunk
   */
  async sendStream<T>(
    command: string,
    params: Record<string, unknown>,
    onData: (data: T) => void
  ): Promise<void> {
    if (!this.connected || !this.socket) {
      throw new Error('Not connected to IPC server');
    }

    return new Promise((resolve, reject) => {
      if (!this.socket) {
        reject(new Error('Socket not available'));
        return;
      }

      const requestId = Date.now();

      // JSON-RPC 2.0 format for streaming
      const message = JSON.stringify({
        jsonrpc: '2.0',
        id: requestId,
        method: command,
        params: params
      });

      logger.debug('ipc_send_stream', {
        command,
        request_id: requestId,
        params_count: Object.keys(params).length,
      });

      let buffer = '';
      let streamEnded = false;

      // Stream timeout (longer than normal)
      const streamTimeout = setTimeout(() => {
        if (!streamEnded) {
          this.socket?.off('data', onStreamData);
          this.socket?.off('error', onError);
          logger.error('ipc_stream_timeout', {
            command,
            request_id: requestId,
            timeout_ms: 180000,
          });
          reject(new Error(`Stream timeout after 180s for command: ${command}`));
        }
      }, 180000); // 180s for stream (3 minutes for LLM calls)

      const onStreamData = (data: Buffer) => {
        buffer += data.toString();

        // Process all complete lines
        while (buffer.includes('\n')) {
          const lineEnd = buffer.indexOf('\n');
          const line = buffer.substring(0, lineEnd);
          buffer = buffer.substring(lineEnd + 1);

          if (line.trim()) {
            try {
              const response = JSON.parse(line.trim());

              // Handle JSON-RPC response wrapper
              if (response.jsonrpc === '2.0' && response.id === requestId) {
                if (response.error) {
                  // Error response
                  streamEnded = true;
                  clearTimeout(streamTimeout);
                  this.socket?.off('data', onStreamData);
                  this.socket?.off('error', onError);
                  reject(new Error(response.error.message || 'Stream error'));
                } else if (response.result) {
                  // Stream event wrapped in result
                  const event = response.result;

                  logger.debug('ipc_stream_event', {
                    command,
                    event_type: event.type,
                    event_name: event.event,
                  });

                  // Check for stream end
                  if (event.type === 'result') {
                    streamEnded = true;
                    clearTimeout(streamTimeout);
                    this.socket?.off('data', onStreamData);
                    this.socket?.off('error', onError);

                    // Send final result as complete event
                    onData(event as T);
                    resolve();
                  } else {
                    // Send progress/other events
                    onData(event as T);
                  }
                }
              }
            } catch (e) {
              logger.error('ipc_stream_parse_error', {
                command,
                error: e instanceof Error ? e.message : 'Unknown',
                line_preview: line.substring(0, 100),
              });
            }
          }
        }
      };

      const onError = (error: Error) => {
        streamEnded = true;
        clearTimeout(streamTimeout);
        this.socket?.off('data', onStreamData);
        this.socket?.off('error', onError);
        logger.error('ipc_stream_socket_error', {
          command,
          error: error.message,
        });
        reject(error);
      };

      this.socket.on('data', onStreamData);
      this.socket.once('error', onError);
      this.socket.write(message + '\n');
    });
  }

  /**
   * Check if connected
   */
  isConnected(): boolean {
    return this.connected;
  }
}

// Singleton instance
export const ipcClient = new IPCClient();