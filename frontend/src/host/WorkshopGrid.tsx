import { useCallback, useMemo, useRef } from "react";
import type { MouseEvent } from "react";
import {
  CellStyleModule, ClientSideRowModelModule, ColumnApiModule, DateFilterModule, ModuleRegistry, NumberFilterModule, PaginationModule,
  TextFilterModule, TooltipModule, ValidationModule, themeQuartz,
} from "ag-grid-community";
import type { CellKeyDownEvent, ColDef, FirstDataRenderedEvent, GridSizeChangedEvent, ValueGetterParams } from "ag-grid-community";
import { AgGridReact } from "ag-grid-react";
import type { CustomCellRendererProps } from "ag-grid-react";
import { navigate } from "../navigation";
import {
  NARROW_BREAKPOINT, NARROW_HIDDEN_COLUMNS, PIN_TITLE_MIN_WIDTH, SEATS_NOTE, SETTLEMENT_NOTE, cellNumber, countText, cutoffInstant, cutoffText,
  dateFilterComparator, nullsLast, opensInstant, priceText, settlementText, statusText, visibilityText, visibilityTooltip,
} from "./consoleModel";
import type { ConsoleRow } from "./consoleModel";
import { displayDate } from "./model";

// AG Grid Community modules only (MIT). No enterprise package or licence key.
ModuleRegistry.registerModules([
  ClientSideRowModelModule, PaginationModule, TextFilterModule, NumberFilterModule, DateFilterModule,
  CellStyleModule, ColumnApiModule, TooltipModule,
  ...(import.meta.env.DEV ? [ValidationModule] : []),
]);

const theme = themeQuartz.withParams({
  fontFamily: "var(--tp-font)",
  fontSize: 15,
  foregroundColor: "var(--tp-ink)",
  headerTextColor: "var(--tp-ink)",
  headerFontWeight: 600,
  backgroundColor: "#ffffff",
  borderColor: "var(--tp-line)",
  accentColor: "var(--tp-blue)",
  wrapperBorderRadius: 20,
  browserColorScheme: "light",
});

const openWorkbench = (href: string) => navigate(href);

function TitleCell({ data }: CustomCellRendererProps<ConsoleRow>) {
  if (!data) return null;
  const onClick = (event: MouseEvent<HTMLAnchorElement>) => {
    // Respect new-tab/window gestures; otherwise use in-app navigation.
    if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    event.preventDefault();
    openWorkbench(data.workbenchHref);
  };
  return <a className="console-title-link" href={data.workbenchHref} onClick={onClick} tabIndex={-1}>{data.title}</a>;
}

// Columns whose values come from the per-workshop detail request.
const DETAIL_COLUMNS = new Set(["status", "cutoff", "capacity", "bookings", "seatsAvailable", "settlement"]);

export default function WorkshopGrid({ rows }: { rows: ConsoleRow[] }) {
  const container = useRef<HTMLDivElement>(null);
  const columnDefs = useMemo<ColDef<ConsoleRow>[]>(() => [
    { colId: "title", headerName: "Title", field: "title", pinned: "left", minWidth: 240, flex: 2,
      cellRenderer: TitleCell, filter: "agTextColumnFilter", comparator: nullsLast },
    { colId: "status", headerName: "Status", valueGetter: (p: ValueGetterParams<ConsoleRow>) => p.data ? statusText(p.data) : null,
      filter: "agTextColumnFilter", comparator: nullsLast, minWidth: 130 },
    { colId: "visibility", headerName: "Visibility", valueGetter: (p) => p.data ? visibilityText(p.data) : null,
      // AG Grid 36.2 `tooltip` callback (replaces deprecated tooltipValueGetter); undefined = no tooltip.
      tooltip: (p) => visibilityTooltip(p.data),
      filter: "agTextColumnFilter", comparator: nullsLast, minWidth: 190 },
    { colId: "opensAt", headerName: "Opens · London", valueGetter: (p) => p.data ? opensInstant(p.data) : null,
      valueFormatter: (p) => p.data ? displayDate(p.data.opensAt) : "", filter: "agDateColumnFilter",
      filterParams: { comparator: dateFilterComparator }, comparator: nullsLast, minWidth: 230 },
    { colId: "cutoff", headerName: "Cutoff · London", valueGetter: (p) => p.data ? cutoffInstant(p.data) : null,
      valueFormatter: (p) => p.data ? cutoffText(p.data) : "",
      filter: "agDateColumnFilter", filterParams: { comparator: dateFilterComparator }, comparator: nullsLast, minWidth: 300 },
    { colId: "capacity", headerName: "Capacity", type: "numericColumn", valueGetter: (p) => p.data ? cellNumber(p.data.capacity) : null,
      valueFormatter: (p) => p.data ? countText(p.data.capacity) : "", filter: "agNumberColumnFilter", comparator: nullsLast, minWidth: 120 },
    { colId: "bookings", headerName: "Bookings", headerTooltip: "Admitted bookings", type: "numericColumn",
      valueGetter: (p) => p.data ? cellNumber(p.data.bookings) : null,
      valueFormatter: (p) => p.data ? countText(p.data.bookings) : "", filter: "agNumberColumnFilter", comparator: nullsLast, minWidth: 150 },
    { colId: "seatsAvailable", headerName: "Seats available*", headerTooltip: SEATS_NOTE, type: "numericColumn",
      valueGetter: (p) => p.data ? cellNumber(p.data.seatsAvailable) : null,
      valueFormatter: (p) => p.data ? countText(p.data.seatsAvailable) : "", filter: "agNumberColumnFilter", comparator: nullsLast, minWidth: 160 },
    { colId: "price", headerName: "Price", type: "numericColumn", valueGetter: (p) => p.data ? p.data.priceMinor / 100 : null,
      valueFormatter: (p) => p.data ? priceText(p.data) : "", filter: "agNumberColumnFilter",
      filterParams: { buttons: ["clear"] }, headerTooltip: "Filter in pounds (GBP)", comparator: nullsLast, minWidth: 120 },
    { colId: "settlement", headerName: "Settlement†", headerTooltip: SETTLEMENT_NOTE,
      valueGetter: (p) => p.data ? settlementText(p.data) : null,
      filter: "agTextColumnFilter", comparator: nullsLast, minWidth: 340, flex: 2 },
  ], []);

  const defaultColDef = useMemo<ColDef<ConsoleRow>>(() => ({
    sortable: true, resizable: true, floatingFilter: true, flex: 1, suppressHeaderMenuButton: false,
    cellClassRules: { "console-unavailable": (p) => p.data?.detail === "failed" && DETAIL_COLUMNS.has(p.column.getColId()) },
  }), []);

  const onCellKeyDown = useCallback((event: CellKeyDownEvent<ConsoleRow>) => {
    const key = (event.event as KeyboardEvent | null | undefined)?.key;
    if (key === "Enter" && event.column.getColId() === "title" && event.data) openWorkbench(event.data.workbenchHref);
  }, []);

  const fitColumns = useCallback((event: GridSizeChangedEvent<ConsoleRow> | FirstDataRenderedEvent<ConsoleRow>) => {
    const width = "clientWidth" in event ? event.clientWidth : container.current?.clientWidth ?? window.innerWidth;
    event.api.setColumnsVisible([...NARROW_HIDDEN_COLUMNS], width >= NARROW_BREAKPOINT);
    event.api.setColumnsPinned(["title"], width >= PIN_TITLE_MIN_WIDTH ? "left" : null);
  }, []);

  return <div className="console-grid" ref={container}>
    <AgGridReact<ConsoleRow>
      theme={theme}
      rowData={rows}
      columnDefs={columnDefs}
      defaultColDef={defaultColDef}
      getRowId={(p) => p.data.workshopId}
      domLayout="autoHeight"
      pagination
      paginationPageSize={10}
      paginationPageSizeSelector={[10, 25, 50]}
      ensureDomOrder
      tooltipShowDelay={300}
      onCellKeyDown={onCellKeyDown}
      onGridSizeChanged={fitColumns}
      onFirstDataRendered={fitColumns}
      suppressColumnVirtualisation
      overlayNoRowsTemplate="<span role='status'>No workshops match the current filters.</span>"
    />
  </div>;
}
