"""
report_generator.py -- Auto-generate Markdown engineering reports from OLGA analysis results.

Usage as a library:
    from report_generator import ReportGenerator
    rg = ReportGenerator(title="My Report")
    rg.add_case_summary('case.genkey')
    rg.add_result_summary('case.tpl')
    rg.add_criterion_evaluation('case.ppl', 'case.genkey', 'FP', 'PIPE-7', 1.35)
    rg.add_figure('plot.png', caption='HOL Profile')
    rg.generate('report.md')

Standalone usage:
    python report_generator.py case.genkey [--results case.tpl] [--ppl case.ppl] \\
        [--criterion 1.35 --flowpath FP --pipe PIPE-7] \\
        [--title "My Report"] -o report.md
"""

import os
import sys
import argparse
import subprocess
from datetime import date
from pathlib import Path

# ---------------------------------------------------------------------------
# Ensure sibling scripts are importable
# ---------------------------------------------------------------------------
_SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)


# ---------------------------------------------------------------------------
# Subprocess helpers for calling sibling summarizers
# ---------------------------------------------------------------------------

def _run_script(script_name, *args):
    """Run a sibling script via subprocess, return stdout text."""
    script_path = os.path.join(_SCRIPTS_DIR, script_name)
    result = subprocess.run(
        [sys.executable, script_path] + list(args),
        capture_output=True,
        text=True,
        encoding='utf-8',
        errors='replace',
    )
    return result.stdout, result.stderr, result.returncode


def _genkey_summary(genkey_path):
    """Return summary text from genkey_summarizer."""
    try:
        from genkey_summarizer import GenkeySummarizer
        from genkey_parser import GenkeyParser
        parser = GenkeyParser(genkey_path)
        summarizer = GenkeySummarizer(parser)
        return summarizer.summarize()
    except Exception:
        stdout, stderr, _ = _run_script('genkey_summarizer.py', genkey_path)
        return stdout if stdout else stderr


def _result_summary(tpl_or_ppl_path):
    """Return summary text from result_summarizer."""
    try:
        from result_summarizer import ResultSummarizer
        summarizer = ResultSummarizer(tpl_or_ppl_path)
        return summarizer.summarize()
    except Exception:
        stdout, stderr, _ = _run_script('result_summarizer.py', tpl_or_ppl_path)
        return stdout if stdout else stderr


def _criterion_table(ppl_path, genkey_path, flowpath, pipe_label,
                     criterion_litres, timestep=None):
    """Return a Markdown table string from criterion_evaluator results."""
    try:
        from criterion_evaluator import CriterionEvaluator
        ev = CriterionEvaluator(ppl_path, genkey_path, flowpath, pipe_label,
                                criterion_litres)
        result = ev.evaluate(timestep=timestep)
        return _format_criterion_table(result)
    except Exception:
        args = [ppl_path, genkey_path, flowpath, pipe_label,
                str(criterion_litres), '--json']
        if timestep is not None:
            args += ['--timestep', str(timestep)]
        stdout, stderr, _ = _run_script('criterion_evaluator.py', *args)
        if stdout:
            try:
                import json
                result = json.loads(stdout)
                return _format_criterion_table(result)
            except Exception:
                pass
        return f"```\n{stdout or stderr}\n```"


def _format_criterion_table(result):
    """Convert a criterion evaluator result dict to a Markdown table."""
    verdict = result.get('verdict', '?')
    liqc = result.get('liqc_litres', float('nan'))
    criterion = result.get('criterion_litres', float('nan'))
    ratio = result.get('ratio', float('nan'))
    timestep = result.get('timestep', '?')
    pipe = result.get('pipe_label', '?')
    pipe_vol = result.get('pipe_volume_litres', float('nan'))
    fill = result.get('fill_fraction', float('nan'))

    verdict_badge = '**PASS**' if verdict == 'PASS' else '**FAIL**'

    lines = [
        '| Parameter | Value |',
        '|-----------|-------|',
        f'| Verdict | {verdict_badge} |',
        f'| Pipe | {pipe} |',
        f'| Timestep | {_fmt_num(timestep)} s |',
        f'| Liquid Content (LIQC) | {_fmt_num(liqc):.3f} L |',
        f'| Criterion | {_fmt_num(criterion):.3f} L |',
        f'| Ratio (LIQC / Criterion) | {_fmt_num(ratio):.2f}x |',
        f'| Pipe Volume | {_fmt_num(pipe_vol):.3f} L |',
        f'| Fill Fraction | {_fmt_pct(fill)} |',
    ]
    return '\n'.join(lines)


def _fmt_num(v):
    """Safe numeric formatter; returns value or '?' on error."""
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _fmt_pct(v):
    """Format a fraction as a percentage string."""
    try:
        return f'{float(v) * 100.0:.1f}%'
    except (TypeError, ValueError):
        return '?'


# ---------------------------------------------------------------------------
# Figure path helper
# ---------------------------------------------------------------------------

def _rel_figure_path(figure_path, report_path):
    """Return figure_path relative to the directory of report_path.

    If report_path is None or relative computation fails, return figure_path
    as-is (absolute or as given).  Uses forward slashes for Markdown portability.
    """
    if report_path is None:
        return str(figure_path).replace('\\', '/')
    try:
        fig = Path(figure_path).resolve()
        rep_dir = Path(report_path).resolve().parent
        rel = fig.relative_to(rep_dir)
        return str(rel).replace('\\', '/')
    except ValueError:
        # figure is on a different drive or outside the report directory
        return str(figure_path).replace('\\', '/')


# ---------------------------------------------------------------------------
# ReportGenerator
# ---------------------------------------------------------------------------

class ReportGenerator:
    """Auto-generate Markdown engineering reports from OLGA analysis results.

    Parameters
    ----------
    title : str
        Report title used as the top-level heading.
    """

    def __init__(self, title="OLGA Analysis Report"):
        self._title = title
        self._sections = []  # list of (heading, content) tuples

    # ------------------------------------------------------------------
    # Section builders
    # ------------------------------------------------------------------

    def add_case_summary(self, genkey_path):
        """Run genkey_summarizer on genkey_path, add as 'Case Summary' section."""
        text = _genkey_summary(genkey_path)
        self._sections.append(('Case Summary', f'```\n{text.strip()}\n```'))

    def add_result_summary(self, tpl_or_ppl_path):
        """Run result_summarizer on tpl_or_ppl_path, add as 'Results Summary' section."""
        text = _result_summary(tpl_or_ppl_path)
        self._sections.append(('Results Summary', f'```\n{text.strip()}\n```'))

    def add_criterion_evaluation(self, ppl_path, genkey_path, flowpath,
                                 pipe_label, criterion_litres, timestep=None):
        """Run criterion_evaluator, add PASS/FAIL table as 'Criterion Evaluation' section."""
        table = _criterion_table(ppl_path, genkey_path, flowpath, pipe_label,
                                 criterion_litres, timestep=timestep)
        self._sections.append(('Criterion Evaluation', table))

    def add_figure(self, figure_path, caption=""):
        """Add embedded figure reference as an image link in Markdown."""
        # Defer path relativisation to generate() where the output path is known.
        # Store raw path; generate() will resolve it.
        self._sections.append(('__figure__', (str(figure_path), caption)))

    def add_custom_section(self, heading, content):
        """Add an arbitrary Markdown section."""
        self._sections.append((heading, content))

    # ------------------------------------------------------------------
    # Output
    # ------------------------------------------------------------------

    def to_string(self, output_path=None):
        """Return the assembled report as a string.

        Parameters
        ----------
        output_path : str or None
            When provided, figure paths are made relative to this file.
        """
        today = date.today().strftime('%Y-%m-%d')
        parts = [
            f'# {self._title}',
            '',
            f'**Date:** {today} | **Generated by:** olga-copilot',
            '',
        ]

        # Group consecutive figures under a single 'Figures' heading.
        # Other sections get their own ## heading.
        i = 0
        while i < len(self._sections):
            heading, content = self._sections[i]

            if heading == '__figure__':
                # Collect all adjacent figures
                fig_lines = []
                while i < len(self._sections) and self._sections[i][0] == '__figure__':
                    _, (fig_path, caption) = self._sections[i]
                    rel = _rel_figure_path(fig_path, output_path)
                    alt = caption if caption else Path(fig_path).stem
                    fig_lines.append(f'![{alt}]({rel})')
                    if caption:
                        fig_lines.append(f'*{caption}*')
                    fig_lines.append('')
                    i += 1
                parts.append('## Figures')
                parts.append('')
                parts.extend(fig_lines)
            else:
                parts.append(f'## {heading}')
                parts.append('')
                parts.append(content)
                parts.append('')
                i += 1

        return '\n'.join(parts)

    def generate(self, output_path):
        """Assemble all sections and write the Markdown report to output_path."""
        report = self.to_string(output_path=output_path)
        output_file = Path(output_path)
        output_file.parent.mkdir(parents=True, exist_ok=True)
        output_file.write_text(report, encoding='utf-8')


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    # Windows cp949 safety: reconfigure stdout to utf-8 before any output.
    if sys.platform == 'win32':
        import io
        try:
            sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        except AttributeError:
            sys.stdout = io.TextIOWrapper(
                sys.stdout.buffer, encoding='utf-8', errors='replace'
            )

    ap = argparse.ArgumentParser(
        description='Generate a Markdown engineering report from OLGA analysis results.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            'Examples:\n'
            '  python report_generator.py case.genkey -o report.md\n'
            '  python report_generator.py case.genkey --results case.tpl -o report.md\n'
            '  python report_generator.py case.genkey --ppl case.ppl\n'
            '      --criterion 1.35 --flowpath FP --pipe PIPE-7 -o report.md\n'
        ),
    )
    ap.add_argument('genkey', nargs='?',
                    help='Path to .genkey input file (optional)')
    ap.add_argument('--results', metavar='FILE',
                    help='Path to .tpl or .ppl result file for Results Summary')
    ap.add_argument('--ppl', metavar='FILE',
                    help='Path to .ppl file for Criterion Evaluation')
    ap.add_argument('--criterion', type=float, metavar='LITRES',
                    help='Criterion threshold in litres (requires --ppl, --flowpath, --pipe)')
    ap.add_argument('--flowpath', metavar='FP',
                    help='Flowpath TAG label (required with --criterion)')
    ap.add_argument('--pipe', metavar='LABEL',
                    help='Pipe label within flowpath (required with --criterion)')
    ap.add_argument('--timestep', type=float, metavar='S',
                    help='Timestep (s) for criterion evaluation (default: last)')
    ap.add_argument('--title', default='OLGA Analysis Report',
                    help='Report title (default: "OLGA Analysis Report")')
    ap.add_argument('-o', '--output', metavar='FILE', required=True,
                    help='Output Markdown file path')
    args = ap.parse_args()

    # Validate criterion dependencies
    if args.criterion is not None:
        missing = []
        if not args.ppl:
            missing.append('--ppl')
        if not args.genkey:
            missing.append('genkey')
        if not args.flowpath:
            missing.append('--flowpath')
        if not args.pipe:
            missing.append('--pipe')
        if missing:
            ap.error(
                '--criterion requires: ' + ', '.join(missing)
            )

    rg = ReportGenerator(title=args.title)

    # Case Summary
    if args.genkey:
        if not Path(args.genkey).exists():
            print('Error: genkey file not found: %s' % args.genkey, file=sys.stderr)
            sys.exit(2)
        try:
            rg.add_case_summary(args.genkey)
        except Exception as e:
            print('Warning: case summary failed: %s' % e, file=sys.stderr)

    # Results Summary
    if args.results:
        if not Path(args.results).exists():
            print('Error: results file not found: %s' % args.results, file=sys.stderr)
            sys.exit(2)
        try:
            rg.add_result_summary(args.results)
        except Exception as e:
            print('Warning: result summary failed: %s' % e, file=sys.stderr)

    # Criterion Evaluation
    if args.criterion is not None:
        if not Path(args.ppl).exists():
            print('Error: ppl file not found: %s' % args.ppl, file=sys.stderr)
            sys.exit(2)
        try:
            rg.add_criterion_evaluation(
                args.ppl, args.genkey, args.flowpath, args.pipe,
                args.criterion, timestep=args.timestep,
            )
        except Exception as e:
            print('Warning: criterion evaluation failed: %s' % e, file=sys.stderr)

    try:
        rg.generate(args.output)
        print('Report written to: %s' % args.output)
        sys.exit(0)
    except Exception as e:
        print('Error: failed to write report: %s' % e, file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
