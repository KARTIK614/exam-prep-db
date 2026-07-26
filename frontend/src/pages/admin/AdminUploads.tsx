import { useState } from 'react';
import { Loader2 } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { adminApi, useAdminUploads } from '@/lib/api/admin';

/**
 * AdminUploads — PDF upload + extraction preview + import.
 * Skeletal wiring; full multi-step preview UI lands in Phase 11.
 */
export default function AdminUploads() {
  const uploads = useAdminUploads();
  const [file, setFile] = useState<File | null>(null);
  const [uploading, setUploading] = useState(false);

  const upload = async () => {
    if (!file) return;
    setUploading(true);
    try {
      const form = new FormData();
      form.append('pdf', file);
      await adminApi.uploadPdf(form);
      uploads.refetch();
    } finally {
      setUploading(false);
    }
  };

  return (
    <div className="mx-auto max-w-4xl space-y-4 pb-16">
      <h1 className="text-2xl font-semibold">PDF uploads</h1>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Upload a PDF</CardTitle>
        </CardHeader>
        <CardContent className="space-y-2">
          <input
            type="file"
            accept="application/pdf"
            onChange={(e) => setFile(e.target.files?.[0] ?? null)}
            className="text-sm"
          />
          <Button onClick={upload} disabled={!file || uploading}>
            {uploading ? 'Uploading…' : 'Upload'}
          </Button>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Recent uploads</CardTitle>
        </CardHeader>
        <CardContent>
          {uploads.isLoading ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : uploads.data?.items?.length ? (
            <ul className="divide-y divide-border text-sm">
              {uploads.data.items.map((u) => (
                <li key={u.id} className="flex items-center justify-between py-2">
                  <span>{u.filename}</span>
                  <span className="text-xs text-muted-foreground">
                    {u.status} · {u.uploaded_at}
                  </span>
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-sm text-muted-foreground">No uploads yet.</p>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
