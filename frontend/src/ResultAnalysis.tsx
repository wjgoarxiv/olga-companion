import { FileImage } from 'lucide-react';
import type { CsvExport, PublicationExport, ResultFile, Series } from './session';
import { useLocale } from './i18n/index.ts';
import NativeSaveAsAction from './NativeSaveAsAction';
import { metric } from './resultPresentation';
import { formatUnit } from './formatUnit';
import { useSignificantFigures } from './useSignificantFigures';
import { Button } from './ui/Button';
import { OperationStatus } from './ui/OperationStatus';
import { Receipt } from './ui/Receipt';

type ResultAnalysisProps = {
  readonly selected: ResultFile;
  /** Null for spatial profiles: export actions stay, trend stats are skipped. */
  readonly series: Series | null;
  /** Figure receipt meta for stats-free (profile) publications. */
  readonly figureMeta?: string | null;
  readonly loading: boolean;
  readonly publication: PublicationExport | null;
  readonly csvExport: CsvExport | null;
  readonly figureExportLoading: boolean;
  readonly csvExportLoading: boolean;
  readonly figureExportError: string;
  readonly csvExportError: string;
  readonly exportPlot: () => void;
  readonly exportCsv: () => void;
};

export default function ResultAnalysis({
  selected,
  series,
  figureMeta,
  loading,
  publication,
  csvExport,
  figureExportLoading,
  csvExportLoading,
  figureExportError,
  csvExportError,
  exportPlot,
  exportCsv,
}: ResultAnalysisProps) {
  const significantFigures = useSignificantFigures();
  const { t } = useLocale();
  return (
    <div className="result-analysis" aria-label={t('analysis.aria')}>
      <div className="result-analysis-head">
        <span>{t('analysis.title')}</span>
        <div className="result-analysis-actions">
          <Button
            variant="secondary"
            className="result-export"
            onClick={exportPlot}
            disabled={loading}
            busy={figureExportLoading}
            busyLabel={t('analysis.creatingFigure') ?? 'Creating figure…'}
            icon={<FileImage size={15} />}
            title={t('analysis.figureTitle')}
          >
            {t('analysis.exportFigure')}
          </Button>
          <Button
            variant="secondary"
            className="result-export"
            onClick={exportCsv}
            disabled={loading}
            busy={csvExportLoading}
            busyLabel={t('analysis.creatingCsv') ?? 'Creating CSV…'}
          >
            {t('analysis.exportCsv')}
          </Button>
        </div>
      </div>
      {series !== null && (
        <>
          <dl>
            <div><dt>{t('analysis.range')}</dt><dd>{t('analysis.rangeLine', { min: metric(series.analysis.minimum, significantFigures), max: metric(series.analysis.maximum, significantFigures), unit: series.unit ?? '' })}</dd></div>
            <div><dt>{t('analysis.final')}</dt><dd>{metric(series.analysis.final, significantFigures)} {formatUnit(series.unit ?? '')}</dd></div>
            <div><dt>{t('analysis.netChange')}</dt><dd>{metric(series.analysis.delta, significantFigures)} {formatUnit(series.unit ?? '')}</dd></div>
            <div><dt>{t('analysis.direction')}</dt><dd>{series.analysis.direction}</dd></div>
            <div><dt>{t('analysis.peakTime')}</dt><dd>{metric(series.analysis.peak_time, significantFigures)} {formatUnit(series.time_unit ?? '')}</dd></div>
            <div><dt>{t('analysis.samples')}</dt><dd>{series.analysis.samples}</dd></div>
          </dl>
          <p>{t('analysis.note')}</p>
        </>
      )}
      {figureExportError && <OperationStatus tone="error" title={t('analysis.figureFailed') ?? 'Figure export failed'} detail={figureExportError} action={<Button variant="secondary" onClick={exportPlot} busy={figureExportLoading} busyLabel={t('analysis.creatingFigure') ?? 'Creating figure…'}>{t('analysis.retryFigure') ?? 'Retry figure'}</Button>} />}
      {csvExportError && <OperationStatus tone="error" title={t('analysis.csvFailed') ?? 'CSV export failed'} detail={csvExportError} action={<Button variant="secondary" onClick={exportCsv} busy={csvExportLoading} busyLabel={t('analysis.creatingCsv') ?? 'Creating CSV…'}>{t('analysis.retryCsv') ?? 'Retry CSV'}</Button>} />}
      <div className="result-export-receipts" aria-live="polite" aria-atomic="false">
        {publication && (
          <Receipt
            title={t('analysis.figureReady') ?? 'Figure export ready'}
            meta={figureMeta ?? (publication.publication ? `${publication.publication.font_family} · ${publication.publication.dpi} dpi` : '')}
            actions={(
              <>
                {publication.plots[0] && <NativeSaveAsAction artifact={publication.plots[0]} label={t('analysis.savePng') ?? 'Save PNG as…'} />}
                {publication.documents[0] && <NativeSaveAsAction artifact={publication.documents[0]} label={t('analysis.savePdf') ?? 'Save PDF as…'} />}
              </>
            )}
          />
        )}
        {csvExport && (
          <Receipt
            title={t('analysis.csvReady') ?? 'CSV export ready'}
            meta={`${csvExport.variable} · ${csvExport.position}${csvExport.unit ? ` · ${formatUnit(csvExport.unit)}` : ''} · ${t('analysis.rows', { count: csvExport.row_count }) ?? `${csvExport.row_count} rows`}`}
            actions={<NativeSaveAsAction artifact={csvExport.download_path} label={t('analysis.saveCsv') ?? 'Save CSV as…'} />}
          />
        )}
      </div>
    </div>
  );
}
