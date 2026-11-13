// Sample flowline for the README: mass source, pipe sections, pressure sink.
// Geometry in the labels matches the README sample case (120 mm, horizontal).
// Section boxes are a drawing of the division, not a count of the case's sections.
import { mkdirSync, writeFileSync } from "node:fs";
import { join, resolve } from "node:path";
const lib = process.env.LIT_SCHEMATIC_LIB;
if (!lib) throw new Error("LIT_SCHEMATIC_LIB must point at lit-schematic scripts/lib");
const { createFigure } = await import(new URL("./figure.mjs", `file://${lib.replace(/\/$/, "")}/`).href);
const S = await import(new URL("./pid.mjs", `file://${lib.replace(/\/$/, "")}/`).href);

const out = resolve(process.argv[2] ?? ".");
const fig = createFigure({
  width: "double",
  height: 72,
  title: "Sample flowline",
  desc: "A mass source feeds a horizontal pipe drawn as OLGA sections and leaves at a pressure sink. The 120 mm label is the README sample case. The five boxes show the section division, not that case's section count.",
});

const a = fig.panel("a", [0, 0, 178, 58]);
const c = a.canvas({ box: [6, 14, 172, 52] });

const ports = { in: ["left", 0.5], out: ["right", 0.5] };
const source = c.add(S.unit({
  x: 18, y: 32, w: 24, h: 14,
  name: "Mass source",
  caption: "Source",
  ports,
}));
const xs = [46, 66, 86, 106, 126];
const sections = xs.map((x, i) => c.add(S.unit({
  x, y: 32, w: 14, h: 12,
  caption: String(i + 1),
  ports,
})));
const sink = c.add(S.unit({
  x: 156, y: 32, w: 22, h: 14,
  name: "Pressure sink",
  caption: "Sink",
  ports,
}));

let prev = source;
for (const section of sections) {
  c.stream({ from: prev.port("out"), to: section.port("in"), role: "liquid" });
  prev = section;
}
c.stream({ from: prev.port("out"), to: sink.port("in"), role: "liquid" });

a.text(8, 12, "OLGA sections", { size: 2.6, bold: true });
a.text(90, 12, "120 mm ID, sample", { size: 2.6, anchor: "start" });

fig.key(["liquid"], [8, 66], { columns: 1, colWidth: 40 });

mkdirSync(out, { recursive: true });
const file = join(out, "flowline.svg");
writeFileSync(file, fig.render());
for (const warning of fig.warnings()) console.warn(`WARN ${warning}`);
console.log(file);
