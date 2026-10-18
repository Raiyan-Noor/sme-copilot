import React from 'react';

/** Data table. Maps to shadcn/ui Table. Numeric columns right-align with tabular figures. */
export function Table({ columns = [], rows = [], rowKey, onRowClick, density = 'regular', caption, empty = 'Nothing here yet.', className = '' }) {
  return (
    <div className={`kc-table-wrap ${className}`}>
      <table className={`kc-table kc-table--${density}`}>
        {caption ? <caption className="kc-table__caption">{caption}</caption> : null}
        <thead>
          <tr>{columns.map((c) => <th key={c.key} style={{ textAlign: c.align || 'left', width: c.width }}>{c.header}</th>)}</tr>
        </thead>
        <tbody>
          {rows.length === 0 ? (
            <tr><td colSpan={columns.length} className="kc-table__empty">{empty}</td></tr>
          ) : rows.map((r, i) => (
            <tr key={rowKey ? r[rowKey] : i} onClick={onRowClick ? () => onRowClick(r) : undefined} className={onRowClick ? 'kc-table__row--click' : undefined}>
              {columns.map((c) => (
                <td key={c.key} style={{ textAlign: c.align || 'left' }} className={c.align === 'right' ? 'kc-table__num' : undefined}>
                  {c.render ? c.render(r) : r[c.key]}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
