export interface TableColumn {
  readonly key: string;
  readonly header: string;
  readonly numeric?: boolean;
}

export function Table({
  columns,
  rows,
  ariaLabel,
  caption,
}: {
  readonly columns: readonly TableColumn[];
  readonly rows: ReadonlyArray<Readonly<Record<string, React.ReactNode>>>;
  readonly ariaLabel: string;
  readonly caption?: string;
}) {
  return (
    <table className="ui-table" aria-label={ariaLabel}>
      {caption && <caption className="ui-table-caption">{caption}</caption>}
      <thead>
        <tr>
          {columns.map((column, index) => (
            <th key={column.key} scope="col" className={column.numeric ? 'ui-num' : undefined}>
              {index > 0 && <i className="pixel-sep th-sep" aria-hidden="true" />}
              {column.header}
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {rows.map((row, index) => (
          <tr key={index}>
            {columns.map((column) => (
              <td key={column.key} className={column.numeric ? 'ui-num' : undefined}>
                {row[column.key]}
              </td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  );
}
