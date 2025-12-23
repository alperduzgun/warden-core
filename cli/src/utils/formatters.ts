/**
 * Formatting Utilities
 *
 * Common formatting functions for Warden CLI
 */

/**
 * Format duration in milliseconds to human-readable string
 *
 * @param ms - Duration in milliseconds
 * @returns Formatted string (e.g., "1m 23s", "45s", "2h 15m")
 *
 * @example
 * ```ts
 * formatDuration(1500) // "1s"
 * formatDuration(65000) // "1m 5s"
 * formatDuration(3661000) // "1h 1m"
 * ```
 */
export function formatDuration(ms: number): string {
  const seconds = Math.floor(ms / 1000);
  const minutes = Math.floor(seconds / 60);
  const hours = Math.floor(minutes / 60);

  if (hours > 0) {
    const remainingMinutes = minutes % 60;
    return remainingMinutes > 0 ? `${hours}h ${remainingMinutes}m` : `${hours}h`;
  }

  if (minutes > 0) {
    const remainingSeconds = seconds % 60;
    return remainingSeconds > 0
      ? `${minutes}m ${remainingSeconds}s`
      : `${minutes}m`;
  }

  return `${seconds}s`;
}

/**
 * Format bytes to human-readable size
 *
 * @param bytes - Size in bytes
 * @param decimals - Number of decimal places (default: 2)
 * @returns Formatted string (e.g., "1.5 KB", "2.3 MB")
 *
 * @example
 * ```ts
 * formatBytes(1024) // "1.00 KB"
 * formatBytes(1536, 1) // "1.5 KB"
 * formatBytes(1048576) // "1.00 MB"
 * ```
 */
export function formatBytes(bytes: number, decimals: number = 2): string {
  if (bytes === 0) return '0 Bytes';

  const k = 1024;
  const dm = decimals < 0 ? 0 : decimals;
  const sizes = ['Bytes', 'KB', 'MB', 'GB', 'TB'];

  const i = Math.floor(Math.log(bytes) / Math.log(k));

  return `${parseFloat((bytes / Math.pow(k, i)).toFixed(dm))} ${sizes[i]}`;
}

/**
 * Format percentage with precision
 *
 * @param current - Current value
 * @param total - Total value
 * @param decimals - Number of decimal places (default: 0)
 * @returns Formatted percentage string
 *
 * @example
 * ```ts
 * formatPercentage(50, 100) // "50%"
 * formatPercentage(1, 3, 1) // "33.3%"
 * ```
 */
export function formatPercentage(
  current: number,
  total: number,
  decimals: number = 0
): string {
  if (total === 0) return '0%';
  const percentage = (current / total) * 100;
  return `${percentage.toFixed(decimals)}%`;
}

/**
 * Format number with thousands separator
 *
 * @param num - Number to format
 * @returns Formatted string with commas
 *
 * @example
 * ```ts
 * formatNumber(1000) // "1,000"
 * formatNumber(1234567) // "1,234,567"
 * ```
 */
export function formatNumber(num: number): string {
  return num.toLocaleString('en-US');
}

/**
 * Truncate text with ellipsis
 *
 * @param text - Text to truncate
 * @param maxLength - Maximum length
 * @param ellipsis - Ellipsis string (default: "...")
 * @returns Truncated text
 *
 * @example
 * ```ts
 * truncateText("Hello World", 8) // "Hello..."
 * truncateText("Short", 10) // "Short"
 * ```
 */
export function truncateText(
  text: string,
  maxLength: number,
  ellipsis: string = '...'
): string {
  if (text.length <= maxLength) return text;
  return text.slice(0, maxLength - ellipsis.length) + ellipsis;
}

/**
 * Format timestamp to human-readable string
 *
 * @param timestamp - ISO timestamp or Date object
 * @returns Formatted string (e.g., "2025-12-23 14:30:45")
 *
 * @example
 * ```ts
 * formatTimestamp(new Date()) // "2025-12-23 14:30:45"
 * formatTimestamp("2025-12-23T14:30:45Z") // "2025-12-23 14:30:45"
 * ```
 */
export function formatTimestamp(timestamp: string | Date): string {
  const date = typeof timestamp === 'string' ? new Date(timestamp) : timestamp;

  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, '0');
  const day = String(date.getDate()).padStart(2, '0');
  const hours = String(date.getHours()).padStart(2, '0');
  const minutes = String(date.getMinutes()).padStart(2, '0');
  const seconds = String(date.getSeconds()).padStart(2, '0');

  return `${year}-${month}-${day} ${hours}:${minutes}:${seconds}`;
}

/**
 * Format elapsed time from start timestamp
 *
 * @param startTime - Start time (Date or ISO string)
 * @returns Formatted duration string
 *
 * @example
 * ```ts
 * const start = new Date(Date.now() - 65000);
 * formatElapsedTime(start) // "1m 5s"
 * ```
 */
export function formatElapsedTime(startTime: string | Date): string {
  const start = typeof startTime === 'string' ? new Date(startTime) : startTime;
  const elapsed = Date.now() - start.getTime();
  return formatDuration(elapsed);
}
