import * as React from 'react';

export interface TableColumn<Row = any> {
  key: string;
  header: React.ReactNode;
  /** Use "right" for money and counts. */
  align?: 'left' | 'right' | 'center';
  width?: number | string;
  render?: (row: Row) => React.ReactNode;
}

/**
 * Data table. Maps to shadcn/ui Table. Hairline rows, sentence-case headers, tabular figures.
 * @startingPoint section="Data" subtitle="Transactions / invoices table" viewport="700x280"
 */
export interface TableProps<Row = any> {
  columns: TableColumn<Row>[];
  rows: Row[];
  /** Field used as React key. */
  rowKey?: string;
  onRowClick?: (row: Row) => void;
  /** compact 40px rows, regular 48px. */
  density?: 'compact' | 'regular';
  caption?: React.ReactNode;
  /** Empty-state text. */
  empty?: React.ReactNode;
  className?: string;
}
export declare function Table<Row = any>(props: TableProps<Row>): JSX.Element;
