import React from 'react';
import {
  ChevronLeft,
  ChevronRight,
  ArrowUpDown,
  ArrowUp,
  ArrowDown,
  Search,
  X,
} from 'lucide-react';
import { TableColumn } from '../../types';
import { SkeletonTable } from './Skeleton';
import { EmptyState } from './EmptyState';
import { ErrorState } from './ErrorState';

export interface DataTableProps<T> {
  columns: TableColumn<T>[];
  data: T[];
  totalCount?: number;
  page?: number;
  pageSize?: number;
  onPageChange?: (newPage: number) => void;
  onPageSizeChange?: (newPageSize: number) => void;
  isLoading?: boolean;
  error?: string | Error | null;
  onRetry?: () => void;
  emptyTitle?: string;
  emptyMessage?: string;
  stickyHeader?: boolean;
  onRowClick?: (row: T) => void;
  searchValue?: string;
  onSearchChange?: (val: string) => void;
  searchPlaceholder?: string;
  filterSlot?: React.ReactNode;
  actionSlot?: React.ReactNode;
  sortColumn?: string;
  sortDirection?: 'asc' | 'desc';
  onSort?: (key: string) => void;
  rowKey?: (row: T, index: number) => string;
  className?: string;
}

export function DataTable<T extends Record<string, any>>({
  columns,
  data,
  totalCount,
  page = 1,
  pageSize = 10,
  onPageChange,
  onPageSizeChange,
  isLoading = false,
  error = null,
  onRetry,
  emptyTitle = 'No data records found',
  emptyMessage = 'There are no records matching your active filters.',
  stickyHeader = true,
  onRowClick,
  searchValue,
  onSearchChange,
  searchPlaceholder = 'Search records...',
  filterSlot,
  actionSlot,
  sortColumn,
  sortDirection,
  onSort,
  rowKey,
  className = '',
}: DataTableProps<T>) {
  const actualTotal = totalCount !== undefined ? totalCount : data.length;
  const totalPages = Math.max(1, Math.ceil(actualTotal / pageSize));
  const startItem = actualTotal === 0 ? 0 : (page - 1) * pageSize + 1;
  const endItem = Math.min(page * pageSize, actualTotal);

  const getSortIcon = (key: string) => {
    if (sortColumn !== key) {
      return <ArrowUpDown className="w-3.5 h-3.5 text-slate-400 group-hover:text-slate-600" />;
    }
    return sortDirection === 'asc' ? (
      <ArrowUp className="w-3.5 h-3.5 text-blue-900" />
    ) : (
      <ArrowDown className="w-3.5 h-3.5 text-blue-900" />
    );
  };

  return (
    <div className={`bg-white rounded-lg border border-slate-200 shadow-xs flex flex-col ${className}`}>
      {/* Table Toolbar (Search, Custom Filters, Actions) */}
      {(onSearchChange || filterSlot || actionSlot) && (
        <div className="p-3 sm:p-4 border-b border-slate-200 flex flex-col sm:flex-row gap-3 items-stretch sm:items-center justify-between bg-slate-50/50 rounded-t-lg">
          <div className="flex flex-1 flex-wrap items-center gap-2.5">
            {onSearchChange && (
              <div className="relative min-w-[220px] max-w-sm flex-1">
                <Search className="w-4 h-4 text-slate-400 absolute left-3 top-1/2 -translate-y-1/2 pointer-events-none" />
                <input
                  type="text"
                  value={searchValue || ''}
                  onChange={(e) => onSearchChange(e.target.value)}
                  placeholder={searchPlaceholder}
                  className="w-full pl-9 pr-8 py-1.5 text-xs sm:text-sm bg-white border border-slate-300 rounded-md shadow-2xs focus:outline-none focus:ring-2 focus:ring-blue-800 focus:border-blue-800 transition-colors"
                />
                {searchValue && (
                  <button
                    type="button"
                    onClick={() => onSearchChange('')}
                    className="absolute right-2.5 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-600"
                    aria-label="Clear search"
                  >
                    <X className="w-3.5 h-3.5" />
                  </button>
                )}
              </div>
            )}
            {filterSlot}
          </div>
          {actionSlot && <div className="flex items-center gap-2 shrink-0">{actionSlot}</div>}
        </div>
      )}

      {/* Table Content or States */}
      <div className="overflow-x-auto relative flex-1 min-h-[220px]">
        {isLoading ? (
          <SkeletonTable rows={pageSize > 10 ? 10 : pageSize} cols={columns.length} />
        ) : error ? (
          <div className="p-6">
            <ErrorState
              title="Error Loading Table Data"
              message={typeof error === 'string' ? error : error.message}
              onRetry={onRetry}
            />
          </div>
        ) : data.length === 0 ? (
          <div className="p-6">
            <EmptyState title={emptyTitle} description={emptyMessage} />
          </div>
        ) : (
          <table className="w-full text-left text-xs sm:text-sm border-collapse">
            <thead
              className={`bg-slate-100/90 backdrop-blur-xs text-slate-700 font-bold uppercase tracking-wider text-[11px] border-b border-slate-200 select-none ${
                stickyHeader ? 'sticky top-0 z-10 shadow-2xs' : ''
              }`}
            >
              <tr>
                {columns.map((col) => {
                  const isSortable = col.sortable && onSort;
                  return (
                    <th
                      key={col.key}
                      scope="col"
                      style={col.width ? { width: col.width } : undefined}
                      className={`px-4 py-3 ${
                        col.align === 'center'
                          ? 'text-center'
                          : col.align === 'right'
                          ? 'text-right'
                          : 'text-left'
                      } ${isSortable ? 'cursor-pointer hover:bg-slate-200/70 group' : ''}`}
                      onClick={() => isSortable && onSort(col.key)}
                    >
                      <div
                        className={`inline-flex items-center gap-1.5 ${
                          col.align === 'center'
                            ? 'justify-center'
                            : col.align === 'right'
                            ? 'justify-end'
                            : 'justify-start'
                        }`}
                      >
                        <span>{col.header}</span>
                        {isSortable && getSortIcon(col.key)}
                      </div>
                    </th>
                  );
                })}
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100 bg-white">
              {data.map((row, idx) => {
                const key = rowKey ? rowKey(row, idx) : row.id || String(idx);
                const isClickable = Boolean(onRowClick);

                return (
                  <tr
                    key={key}
                    onClick={() => onRowClick?.(row)}
                    className={`transition-colors ${
                      isClickable
                        ? 'cursor-pointer hover:bg-slate-50 focus-within:bg-blue-50/40'
                        : 'hover:bg-slate-50/60'
                    }`}
                  >
                    {columns.map((col) => {
                      const cellContent = col.accessor
                        ? col.accessor(row)
                        : row[col.key] !== undefined && row[col.key] !== null
                        ? String(row[col.key])
                        : '—';

                      return (
                        <td
                          key={col.key}
                          className={`px-4 py-3 text-slate-800 ${
                            col.align === 'center'
                              ? 'text-center'
                              : col.align === 'right'
                              ? 'text-right'
                              : 'text-left'
                          }`}
                        >
                          {cellContent}
                        </td>
                      );
                    })}
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>

      {/* Pagination Footer */}
      {onPageChange && (
        <div className="px-4 py-3 border-t border-slate-200 bg-slate-50/80 flex flex-col sm:flex-row items-center justify-between gap-3 text-xs text-slate-600 rounded-b-lg">
          <div className="flex items-center gap-2">
            <span>
              Showing <strong className="text-slate-900 font-semibold">{startItem}</strong> to{' '}
              <strong className="text-slate-900 font-semibold">{endItem}</strong> of{' '}
              <strong className="text-slate-900 font-semibold">{actualTotal}</strong> records
            </span>
            {onPageSizeChange && (
              <div className="flex items-center gap-1.5 ml-3 pl-3 border-l border-slate-300">
                <span>Per page:</span>
                <select
                  value={pageSize}
                  onChange={(e) => onPageSizeChange(Number(e.target.value))}
                  className="bg-white border border-slate-300 rounded px-1.5 py-0.5 text-xs text-slate-800 focus:outline-none focus:ring-1 focus:ring-blue-800"
                >
                  <option value={10}>10</option>
                  <option value={25}>25</option>
                  <option value={50}>50</option>
                  <option value={100}>100</option>
                </select>
              </div>
            )}
          </div>

          <div className="flex items-center gap-1">
            <button
              type="button"
              disabled={page <= 1 || isLoading}
              onClick={() => onPageChange(page - 1)}
              className="p-1.5 rounded border border-slate-300 bg-white hover:bg-slate-100 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
              aria-label="Previous page"
            >
              <ChevronLeft className="w-4 h-4" />
            </button>
            <span className="px-2 font-medium text-slate-700">
              Page {page} of {totalPages}
            </span>
            <button
              type="button"
              disabled={page >= totalPages || isLoading}
              onClick={() => onPageChange(page + 1)}
              className="p-1.5 rounded border border-slate-300 bg-white hover:bg-slate-100 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
              aria-label="Next page"
            >
              <ChevronRight className="w-4 h-4" />
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

export default DataTable;
