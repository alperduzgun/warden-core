/**
 * IPC Client for communicating with Warden backend
 * Handles socket connection and message passing
 */

import {createConnection, Socket} from 'node:net';
import type {IPCResponse} from './types.js';
import {logger} from '../utils/logger.js';

const IPC_SOCKET_PATH = '/tmp/warden-ipc.sock';
const CONNECTION_TIMEOUT = 10000; // Increased from 5s to 10s
const RESPONSE_TIMEOUT = 15000; // 15s for command responses

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

        // Check if we have a complete line (JSON-RPC uses line-delimited JSON)
        if (buffer.includes('\n')) {
          responseReceived = true;
          clearTimeout(responseTimeout);

          try {
            const jsonRpcResponse = JSON.parse(buffer.trim());
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
            } else {
              logger.debug('ipc_command_success', {command});
              resolve({
                success: true,
                data: jsonRpcResponse.result as T
              });
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
   * Check if connected
   */
  isConnected(): boolean {
    return this.connected;
  }
}

// Singleton instance
export const ipcClient = new IPCClient();
