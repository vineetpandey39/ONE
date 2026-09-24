/**
 * PostForge's cockpit tab: five pillars of last-24-hours AI sources, each one
 * already verified against its own source page before it reaches this list.
 *
 * The board deliberately shows the rejection count next to the verified count.
 * An empty feed with twelve rejections is a healthy verifier, not a broken
 * refresh, and the operator needs to be able to tell those two apart at a
 * glance — so "Rejected stale" is a first-class tile, and every rejection
 * reason is readable underneath.
 */
import { useCallback, useEffect, useMemo, useState } from 'react';
import { CheckCircle2, ExternalLink, Loader2, RefreshCw, ShieldCheck, Sparkles } from 'lucide-react';
import { apiFetch } from '../lib/api';

type Pillar = { id: string; label: string; full: string; color: string };

type SourceItem = {
  id: string;
  tag: string;
  source: string;
  headline: string;
  summary: string;
  url: string;
  date: string;
  publishedAt: string;
  ageHours: number | null;
  verified: boolean;
  verification?: { sourceTitle?: string; headlineScore?: number; summaryScore?: number };
};

type RefreshPayload = {
  pillar: string;
  pillarFull: string;
  items: SourceItem[];
  refreshedAt: string;
  freshnessHours: number;
  rejected: number;
  rejectedReasons: Array<{ url: string; reason: string }>;
  searchCalls: number;
  cached: boolean;
};

type GeneratedSlide = {
  role: string;
  slide_headline: string;
  slide_subline: string;
  body: string;
  source: string;
  source_url: string;
};

type GeneratedPost = {
  hook?: string;
  cover_text?: string;
  cover_subtext?: string;
  caption?: string;
  cta?: string;
  hashtags?: string;
  slides?: GeneratedSlide[];
  _format?: string;
  _verified_sources?: Array<{ source: string; headline: string; url: string; date: string }>;
};

const DEFAULT_PILLARS: Pillar[] = [
  { id: 'news', label: 'News', full: 'AI News Breakdown', color: '#3B82F6' },
  { id: 'tool', label: 'Tools', full: 'AI Tool Drop', color: '#F59E0B' },
  { id: 'income', label: 'Income', full: 'AI Income Update', color: '#10B981' },
  { id: 'transformation', label: 'Transform', full: 'AI Transformation', color: '#8B5CF6' },
  { id: 'automation', label: 'Automation', full: 'AI Automation Win', color: '#38BDF8' },
];

const DEFAULT_FORMATS = ['Carousel', 'Reel Script', 'Story Hook', 'Caption Only'];

async function readError(response: Response): Promise<string> {
  try {
    const body = await response.json();
    return String(body?.detail || body?.error || `Request failed (${response.status})`);
  } catch {
    return `Request failed (${response.status})`;
  }
}

function age(item: SourceItem): string {
  if (item.ageHours === null || item.ageHours === undefined) return 'undated';
  if (item.ageHours < 1) return 'under an hour ago';
  return `${Math.round(item.ageHours)}h ago`;
}

export function PostForgeBoard() {
  const [pillars, setPillars] = useState<Pillar[]>(DEFAULT_PILLARS);
  const [formats, setFormats] = useState<string[]>(DEFAULT_FORMATS);
  const [freshnessHours, setFreshnessHours] = useState(24);
  const [pillarId, setPillarId] = useState('news');
  const [format, setFormat] = useState('Carousel');
  const [feed, setFeed] = useState<RefreshPayload | null>(null);
  const [selected, setSelected] = useState<string[]>([]);
  const [post, setPost] = useState<GeneratedPost | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [message, setMessage] = useState('');

  const pillar = useMemo(
    () => pillars.find((entry) => entry.id === pillarId) || pillars[0],
    [pillars, pillarId],
  );

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const response = await apiFetch('/v1/postforge/pillars');
        if (!response.ok || cancelled) return;
        const data = await response.json();
        if (Array.isArray(data.pillars) && data.pillars.length) setPillars(data.pillars);
        if (Array.isArray(data.formats) && data.formats.length) setFormats(data.formats);
        if (data.freshnessHours) setFreshnessHours(data.freshnessHours);
      } catch {
        // The defaults above keep the board usable while the server is starting.
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  // Sources belong to the tab they were found in, so switching tabs clears the
  // feed rather than showing one pillar's items under another's heading.
  const switchPillar = useCallback((next: string) => {
    setPillarId(next);
    setFeed(null);
    setSelected([]);
    setPost(null);
    setMessage('');
  }, []);

  const refresh = useCallback(async () => {
    setRefreshing(true);
    setMessage('');
    try {
      const response = await apiFetch('/v1/postforge/refresh', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ pillar: pillarId, force: true }),
      });
      if (!response.ok) {
        setMessage(await readError(response));
        return;
      }
      const data: RefreshPayload = await response.json();
      setFeed(data);
      setSelected([]);
      setPost(null);
      if (!data.items.length) {
        setMessage(
          `Nothing published in the last ${data.freshnessHours}h survived verification` +
            (data.rejected ? ` — ${data.rejected} candidate(s) rejected.` : '.'),
        );
      }
    } catch (error) {
      setMessage(`Refresh failed: ${String(error)}`);
    } finally {
      setRefreshing(false);
    }
  }, [pillarId]);

  const generate = useCallback(async () => {
    const items = (feed?.items || []).filter((item) => selected.includes(item.id));
    if (!items.length) return;
    setGenerating(true);
    setMessage('');
    try {
      const response = await apiFetch('/v1/postforge/generate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ pillar: pillarId, format, items }),
      });
      if (!response.ok) {
        setMessage(await readError(response));
        return;
      }
      setPost(await response.json());
    } catch (error) {
      setMessage(`Generation failed: ${String(error)}`);
    } finally {
      setGenerating(false);
    }
  }, [feed, selected, pillarId, format]);

  const toggle = (id: string) =>
    setSelected((current) =>
      current.includes(id) ? current.filter((entry) => entry !== id) : [...current, id],
    );

  const items = feed?.items || [];

  return (
    <section className="one-operations one-postforge-board">
      <div className="one-operations-head">
        <div>
          <div className="one-panel-label">VERIFIED AI CONTENT COCKPIT</div>
          <strong>POSTFORGE SOURCE FEED</strong>
        </div>
        <span className="one-postforge-owner">
          <ShieldCheck size={15} /> Sanjeevani researches · local model writes
        </span>
      </div>

      <div className="one-postforge-tabs" role="tablist" aria-label="Content pillars">
        {pillars.map((entry) => (
          <button
            key={entry.id}
            type="button"
            role="tab"
            aria-selected={entry.id === pillarId}
            className={entry.id === pillarId ? 'active' : ''}
            style={entry.id === pillarId ? { borderColor: entry.color, color: entry.color } : undefined}
            onClick={() => switchPillar(entry.id)}
          >
            {entry.label}
          </button>
        ))}
      </div>

      <div className="one-postforge-controls">
        <select value={format} onChange={(event) => setFormat(event.target.value)} aria-label="Output format">
          {formats.map((entry) => (
            <option key={entry} value={entry}>
              {entry}
            </option>
          ))}
        </select>
        <button type="button" className="primary" disabled={refreshing} onClick={() => void refresh()}>
          {refreshing ? <Loader2 size={15} className="spin" /> : <RefreshCw size={15} />}
          {refreshing ? 'Researching…' : `Refresh ${pillar?.full || ''}`}
        </button>
        <button
          type="button"
          className="generate"
          disabled={generating || !selected.length}
          onClick={() => void generate()}
        >
          {generating ? <Loader2 size={15} className="spin" /> : <Sparkles size={15} />}
          Generate ({selected.length})
        </button>
      </div>

      <div className="one-postforge-summary">
        <div>
          <span>Fresh window</span>
          <strong>{freshnessHours} hours</strong>
        </div>
        <div>
          <span>Verified items</span>
          <strong>{items.length}</strong>
        </div>
        <div>
          <span>Selected</span>
          <strong>{selected.length}</strong>
        </div>
        <div>
          <span>Rejected stale</span>
          <strong>{feed?.rejected ?? 0}</strong>
        </div>
      </div>

      {message && (
        <p className="one-postforge-message" role="status">
          {message}
        </p>
      )}

      <div className="one-postforge-panes">
        <article className="one-postforge-pane">
          <div className="one-panel-label">{(pillar?.full || 'AI NEWS').toUpperCase()}</div>
          <h4>Verified Source Feed</h4>
          {!items.length && (
            <div className="one-postforge-empty">
              <strong>No sources loaded</strong>
              <span>
                Refresh to fetch source-backed items from the last {freshnessHours} hours. Every item
                is re-opened at its own URL and dropped unless the page proves its date and claim.
              </span>
            </div>
          )}
          {items.map((item) => (
            <label key={item.id} className={selected.includes(item.id) ? 'one-postforge-item selected' : 'one-postforge-item'}>
              <input type="checkbox" checked={selected.includes(item.id)} onChange={() => toggle(item.id)} />
              <div>
                <strong>{item.headline}</strong>
                <span className="one-postforge-meta">
                  <CheckCircle2 size={13} /> {item.source} · {age(item)}
                  {item.verification?.headlineScore !== undefined && (
                    <> · match {item.verification.headlineScore}</>
                  )}
                </span>
                <p>{item.summary}</p>
                <a href={item.url} target="_blank" rel="noreferrer noopener">
                  <ExternalLink size={12} /> {item.url}
                </a>
              </div>
            </label>
          ))}
          {!!feed?.rejectedReasons?.length && (
            <details className="one-postforge-rejected">
              <summary>{feed.rejected} rejected by the verifier</summary>
              <ul>
                {feed.rejectedReasons.map((row) => (
                  <li key={row.url}>
                    <code>{row.url}</code>
                    <span>{row.reason}</span>
                  </li>
                ))}
              </ul>
            </details>
          )}
        </article>

        <article className="one-postforge-pane">
          <div className="one-panel-label">CREATION PLAN</div>
          <h4>Generated Output</h4>
          {!post && (
            <div className="one-postforge-empty">
              <strong>No post yet</strong>
              <span>Select verified sources, then generate a {format.toLowerCase()} plan.</span>
            </div>
          )}
          {post && (
            <div className="one-postforge-output">
              {post.hook && (
                <p className="one-postforge-hook">
                  <b>Hook</b> {post.hook}
                </p>
              )}
              {post.cover_text && (
                <p className="one-postforge-cover">
                  {post.cover_text}
                  {post.cover_subtext ? <em>{post.cover_subtext}</em> : null}
                </p>
              )}
              {(post.slides || []).map((slide, index) => (
                <div key={`${slide.role}-${index}`} className="one-postforge-slide">
                  <b>{slide.role.toUpperCase()}</b>
                  <strong>{slide.slide_headline}</strong>
                  <span>{slide.slide_subline}</span>
                  <p>{slide.body}</p>
                  {slide.source_url && (
                    <a href={slide.source_url} target="_blank" rel="noreferrer noopener">
                      {slide.source}
                    </a>
                  )}
                </div>
              ))}
              {post.caption && <p className="one-postforge-caption">{post.caption}</p>}
              {post.cta && <p className="one-postforge-cta">{post.cta}</p>}
              {post.hashtags && <p className="one-postforge-tags">{post.hashtags}</p>}
            </div>
          )}
        </article>
      </div>
    </section>
  );
}
