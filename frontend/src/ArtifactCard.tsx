import { useState } from 'react';
import { useLocale } from './i18n/index.ts';
import type { TranslateFn } from './i18n/index.ts';
import NativeSaveAsAction from './NativeSaveAsAction';
import { requestOpenArtifactInResults } from './artifactNavigation';
import { ArtifactDownloadError, downloadArtifact } from './resultApi';
import { presentArtifactReceipt } from './resultPresentation';
import { Button } from './ui/Button';
import { OperationStatus } from './ui/OperationStatus';
import { Receipt } from './ui/Receipt';

function formatBytes(size: number | undefined, t: TranslateFn): string {
  if (size === undefined) return t('artifact.sizeUnavailable') ?? 'Size unavailable';
  if (size < 1024) return t('saveas.bytesB', { value: size }) ?? `${size} B`;
  if (size < 1024 * 1024) {
    const kb = (size / 1024).toFixed(1);
    return t('saveas.bytesKB', { value: kb }) ?? `${kb} KB`;
  }
  const mb = (size / (1024 * 1024)).toFixed(1);
  return t('saveas.bytesMB', { value: mb }) ?? `${mb} MB`;
}

function saveBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  URL.revokeObjectURL(url);
}

export default function ArtifactCard({
  receipt,
  currentWorkspaceGeneration,
}: {
  readonly receipt: unknown;
  readonly currentWorkspaceGeneration?: number;
}) {
  const presentation = presentArtifactReceipt(receipt, currentWorkspaceGeneration);
  const [downloading, setDownloading] = useState(false);
  const [downloadError, setDownloadError] = useState('');
  const { t } = useLocale();
  if (!presentation) return <p className="error">{t('artifact.unavailable')}</p>;
  const artifact = presentation.receipt;
  const canDownload = presentation.actions.some((action) => action.kind === 'download');
  const canOpen = presentation.actions.some((action) => action.kind === 'open-results')
    && artifact.result_id !== undefined;
  const canSaveAs = presentation.actions.some((action) => action.kind === 'save-as');

  async function download(): Promise<void> {
    setDownloading(true);
    setDownloadError('');
    try {
      const blob = await downloadArtifact(artifact.artifact_id);
      saveBlob(blob, artifact.suggested_filename);
    } catch (error: unknown) {
      setDownloadError(error instanceof ArtifactDownloadError
        ? t('artifact.downloadIncomplete') ?? 'Artifact download could not be completed.'
        : error instanceof Error ? error.message : t('artifact.downloadFailed') ?? 'Artifact download failed.');
    } finally {
      setDownloading(false);
    }
  }

  function openResults(): void {
    const resultId = artifact.result_id;
    if (!resultId) return;
    requestOpenArtifactInResults({
      artifactId: artifact.artifact_id,
      resultId,
    });
  }

  const size = artifact.size_bytes ?? artifact.size;
  const actions = presentation.read_only ? undefined : (
    <>
      {canDownload && <Button variant="secondary" onClick={() => { void download(); }} busy={downloading} busyLabel={t('artifact.downloading') ?? 'Downloading…'}>{t('artifact.download') ?? 'Download'}</Button>}
      {canOpen && <Button variant="quiet" onClick={openResults}>{t('artifact.openInResults') ?? 'Open in Results'}</Button>}
      {canSaveAs && <NativeSaveAsAction artifact={`artifact:${artifact.artifact_id}`} label={t('artifact.saveAs') ?? 'Save As…'} />}
    </>
  );
  return (
    <div className="artifact-card">
      <Receipt
        title={artifact.suggested_filename}
        meta={`${artifact.kind.toUpperCase()} · ${formatBytes(size, t)} · SHA-256 ${artifact.sha256.slice(0, 12)}…`}
        actions={actions}
      >
        {presentation.read_only && <span>{t('artifact.historical') ?? 'Historical artifact · read-only after workspace change'}</span>}
      </Receipt>
      {downloadError && <OperationStatus tone="error" title={t('artifact.downloadFailedTitle') ?? 'Download failed'} detail={downloadError} />}
    </div>
  );
}
