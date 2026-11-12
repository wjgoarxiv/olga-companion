# Pipe tables

A pipe table describes a network one pipe per row. The app reads it, builds the
flowpaths, junctions and valves, divides every pipe into sections, and shows the result
before anything is saved. After one approval it writes a new case file; it never
overwrites an existing one.

Accepted files are `.csv` (comma, semicolon or tab, saved as UTF-8) and `.xlsx`. Excel files
are read as saved: formulas are not recalculated, so save the workbook in Excel before
importing. A template is in [`docs/examples/pipe_table_template.csv`](examples/pipe_table_template.csv).

## Pipe rows

| Column | Meaning |
|---|---|
| `flowpath` | Name of the flowpath this pipe belongs to. Rows of one flowpath are read in table order, inlet first. |
| `pipe` | Name of the pipe (optional, used in messages). |
| `from_node`, `to_node` | Node at the flowpath inlet and outlet. A node shared by two or more flowpaths becomes a junction. |
| `length_m` | Pipe length, greater than zero. |
| `elevation_m` | Height change from the pipe inlet to its outlet (negative for downhill); at most the length. |
| `x_m`, `y_m`, `z_m` | End point of this pipe in metres, as an alternative to `length_m`/`elevation_m`. The pipe length is the 3-D distance from the previous end point and the elevation change is the rise on Y (the vertical axis). A flowpath starts at its first row's start columns (`x_start_m`, `y_start_m`, `z_start_m`, all three together), at the position an already-converted flowpath left at its `from_node`, or — only when no row of the table states a start, for the first such inlet — at the origin; any other unknown start is refused, and the summary flags an assumed origin (`coordinate_origin_assumed`). Two rows that put the same node more than 1 mm apart are refused, as is a start column on a later row that does not match the previous end within 1 mm. One table uses one style: mixing coordinate rows with length rows is refused, and a zero-length pipe is refused. |
| `inner_diameter_m` | Inner diameter, greater than zero. |
| `roughness_m` | Wall roughness. |
| `valve`, `valve_position`, `valve_diameter_m`, `valve_schedule` | Optional valve on this pipe: its name, its place along the pipe (0-1), its diameter (default the pipe diameter) and its opening, either one number (0-1) or `time:opening` pairs such as `0:1, 299:1, 300:0`. |
| `initial_void_fraction` | Optional start void fraction (0-1) of this pipe's flowpath, for example 0 for a pipe full of liquid and 1 for an empty one. Rows of one flowpath that state it must agree, and so must flowpaths joined through a pass-through junction. A flowpath with no value starts at the shared start void fraction. |

Columns may carry a unit instead of `_m`: `length_mm`, `Length (mm)`, `Inner Diameter (mm)`
and `cm` work. Common header spellings are understood (`Line` for flowpath, `Height` for
the elevation change, `From`/`To`, `Inner Diameter`, `Pipe No.`). A column named `ID` or
`Schedule` is not guessed; name it in a column map if it holds a diameter or valve
openings. Other columns are ignored and listed in the import summary. A number written
with a thousands comma, such as `1,500`, is refused rather than guessed.

## Node rows

A row with `node` filled and no `flowpath` gives a boundary:

| Column | Meaning |
|---|---|
| `node` | Node name, as used in `from_node`/`to_node`. |
| `node_kind` | `source` (one outgoing flowpath), `sink` (one incoming flowpath), or `closed` (a flowpath inlet fed by a mass-flow inlet). |
| `pressure_bar` (or `pressure_pa`, `pressure_kpa`) | Boundary pressure (source and sink only). The unit must be in the header. |
| `mass_flow_kg_s` | Mass flow for a `closed` inlet, greater than zero. Missing or zero flow is refused. |
| `temperature_c` | Boundary temperature. |
| `gas_fraction`, `water_fraction` | Phase fractions of the boundary fluid. |

A `closed` node becomes a closed end plus a mass-flow source at section 1 of the
first pipe of its flowpath, using its mass flow, temperature and fractions. A `closed`
node at a flowpath outlet is refused. Every end node needs a node row. The app does not
fill in a pressure, temperature or fraction you did not give.

## Junctions

A junction has exactly one flowpath on one side and up to six on the other (2 to 7 in
all), for example one inlet split into four, or six arms merging into one. A node with
two or more flowpaths on both sides is refused; split it into two junctions with a short
flowpath between them. A node with exactly one flowpath in and one out is not a junction:
the two flowpaths are joined into one, because OLGA 2022 does not solve such a junction.

## Endpoints tables

A table can give each pipe only by its two end points instead of flowpaths and
nodes: one row per pipe with `pipe`, the start (`x_start_m`, `y_start_m`,
`z_start_m`) and end (`x_m`, `y_m`, `z_m`) coordinates, plus `inner_diameter_m`
and `roughness_m`. Start and end spellings such as `Start X (m)` or `X1 (m)`
are understood. Import it with `layout: "endpoints"`, the required
`vertical_axis` (`"y"` when Y points up, `"z"` when Z points up) and, when the
table has no roughness column, one `roughness_m` for every pipe. A template is in
[`docs/examples/pipe_table_endpoints_template.csv`](examples/pipe_table_endpoints_template.csv).

The import joins ends within 1 mm into one node, chains degree-2 runs into one
flowpath in the direction each row is written (rows run with the flow, from
start to end), splits a pipe where another pipe's end touches its middle
within 1 mm so a junction forms there (reported under `split_rows`; a split
row's valve fields stay on the single piece containing the valve position,
and a valve exactly on a split point is refused; a table too large to scan
skips the split pass and reports `split_skipped` instead), and names degree-1 ends
`END_nnn`; the draft lists them with
their sheet-frame coordinates under `ends`, with the merged chains under
`merged_rows`, and every end needs a node row before the case builds.
`flowpath`, `from_node` and `to_node` columns are refused in this mode, because
flowpaths are joined from the coordinates (this also catches label headers
such as Line, Branch, From or To: remove the column or map it away with
`column_map`); a stated `length_m` or `elevation_m`
is only checked against the coordinates, never used. A near miss of 1 mm to
0.1 m (unless a pipe of 0.1 m or less joins the two ends), a loop, two pipes
sharing both ends, and a stated length or rise that
disagrees with the coordinates by more than the larger of 1% and 0.01 m are
refused naming the rows. Without `layout`, `vertical_axis` and `roughness_m`
are ignored. The draft lists at most 100 ends and 50 merged chains; `ends_total`
and `merged_rows_total` give the full counts, and the tool reports at most
20 issues and lists at most 20 boundaries (`boundaries_total` gives the
full count).

## Sections

Each pipe gets at least two sections and none longer than the chosen maximum
(`max_section_m`, 1 m unless you ask for another). Neighbouring sections inside a
flowpath, across pipe boundaries too, stay within a length ratio of `max_ratio`
(2 unless you ask for 1.1-4): the option is both the growth factor of the graded
cells (never above the historical 1.5) and the bar for the ratio warnings. A short
pipe next to a long one makes the long pipe's sections grow gradually instead of being
cut evenly, so a tighter ratio grades more finely where short and long pipes meet,
while a looser one keeps the same mesh and only warns less.
Sections are finer next to valves and at flowpath ends that meet a junction, but never
shorter than half the flowpath's shortest pipe: OLGA's time step follows the shortest
section, so finer cells slow every run. Where that floor and the ratio rule disagree, the
floor wins and the case check warns about the jump. Where the end sections of flowpaths
meeting at one junction differ by more than `max_ratio`, the summary lists it as a warning.

## Start state

A table case starts without OLGA's steady-state pre-processor, which did not converge on
split and merge networks. Every flowpath starts at one pressure and temperature, filled
with the source fluid. State them at import (`initial_conditions`: `pressure_pa`,
`temperature_c`). Without them the case starts at the lowest boundary pressure and the
plain (unweighted) mean inlet temperature and void fraction (sources and `closed`
inlets count; pressure sources have no known flow to weight by), and when the highest boundary pressure is more than 1.5 times the lowest
the draft warns: a start far from the boundary pressures can push the fluid out of the PVT
table's range in the first moment of the run. For the shipped template on the co2_c3 table,
start at 2.2 bar and 25 °C: from there its 2.4 bar source and 2.0 bar sinks stay inside the
table's 1–100 bar, 0–50 °C range.

The `initial_void_fraction` column overrides the void fraction flowpath by flowpath. A
network that is partly full of liquid and partly empty runs far slower from a uniform
half-and-half start. `max_dt_s` at import caps the time step (OLGA `MAXDT`); it is unset
unless stated, and it must be at most a tenth of the end time.

## Limits

One case holds at most 256 nodes, 512 flowpaths, 500 pipes per flowpath, 256 valves and
10,000 sections. A larger table is refused with one message that lists every limit it
passes. A table holds at most 20,000 rows and 256 columns: more rows are refused, and
a cell past column 256 is refused naming the cell. Two node rows for the same node are
refused as a duplicate, naming both rows.

## Draft edits

After the import, the chat edits the draft by id and rebuilds it; a failed rebuild
leaves the draft unchanged:

- `resegment` (`max_section_m`, `max_ratio`);
- `set_valve_schedule` (valve name or label, `time_s`/`opening` points);
- `set_boundary` (`pressure_pa` and/or `temperature_c` on a boundary node);
- `set_fluid` (`pvt_reference` and/or `fluid_label`);
- `set_thermal` (the `thermal` choice);
- `set_end_time` (`end_time_s`).

## Not supported yet

- Restart from a previous run and two-step runs.
- Changing the structure of a case drawn in the OLGA GUI.

## 한국어 요약

배관표는 배관 하나를 한 줄에 적습니다. 유로 이름, 시작·끝 노드, 길이, 높이 변화,
내경, 거칠기가 필수입니다. 길이 대신 끝점 좌표(`x_m`, `y_m`, `z_m`)를 적을 수도
있습니다. 높이는 Y축 변화입니다. 유로의 시작점은 첫 줄의 시작 좌표(세 개를 함께
적습니다), 이미 변환된 유로가 둔 시작 노드 위치, 또는 (표에 시작 좌표가 하나도
없을 때 첫 번째 입구에 한해) 원점입니다. 원점을 가정하면 요약에 표시됩니다.
같은 노드를 1mm 넘게 다르게 두면 거부됩니다. 한 표에서는 한 방식만 씁니다. 밸브는 같은 줄에 이름, 위치(0~1), 지름, 개폐 일정
(`0:1, 299:1, 300:0`)을 적습니다. 경계 조건은 `node` 줄에 적습니다.
종류(source/sink/closed), 압력(헤더에 단위 포함), 온도, 기체 분율과 물 분율이
들어갑니다. closed 입구에는 질량 유량(`mass_flow_kg_s`, 0보다 크고 1e6 이하)을
적습니다. 앱은 구간을 최대 길이 이하로, 이웃 구간 길이 비율(`max_ratio`, 기본 2,
1.1~4)로 자동 분할합니다. `max_ratio`는 구간 증가율(최대 1.5)과 경고 기준을 함께
정합니다. 다만 구간은 그 유로에서 가장 짧은 배관 길이의 절반보다 짧아지지 않습니다.
이 때문에 비율을 넘는 곳은 경고로 알려 줍니다.
시작 압력과 온도는 import할 때 적습니다. 적지 않으면 가장 낮은 경계 압력과 유입
온도·기체 분율의 단순 평균(source와 closed 입구 기준)에서 시작하고, 경계 압력
차이가 1.5배를 넘으면 경고합니다. 동봉된 템플릿을 co2_c3 유체표와 함께 쓸 때는
시작 상태로 2.2 bar / 25 °C를 권장합니다. 2.4 bar 공급원과 2.0 bar 배출구가
유체표 범위(1–100 bar, 0–50 °C) 안에 들어갑니다. 가져온 뒤에는 초안을 고쳐 다시 만들 수 있습니다(
`resegment`, `set_valve_schedule`, `set_boundary`, `set_fluid`, `set_thermal`,
`set_end_time`). 저장 전에 요약과 배관망을 보여 주고, 승인하면 새 파일로만
저장합니다.
끝점 좌표만 적은 표도 가져올 수 있습니다. 배관마다 시작점(`x_start_m`,
`y_start_m`, `z_start_m`)과 끝점(`x_m`, `y_m`, `z_m`), 내경, 거칠기를 적고
`layout: "endpoints"`와 수직축(`vertical_axis`: Y-up이면 `"y"`, Z-up이면
`"z"`)을 함께 넘깁니다. 거칠기 칸이 없으면 `roughness_m` 하나를 넘깁니다.
줄은 흐름 방향으로 적습니다. 1mm 안의 끝점은 한 노드로 묶이고, 막다른 끝은
`END_nnn`으로 목록에 나와 경계 조건(`node`) 줄을 받아야 완성됩니다. 끝점
좌표는 적은 그대로의 축으로 목록에 나옵니다. 목록은 끝점 100개, 묶인
유로 50개까지만 보여 주고 전체 개수는 따로 줍니다.
