import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { CSSProperties, PointerEvent as ReactPointerEvent } from 'react';
import {
  BarChart3,
  BrainCircuit,
  Check,
  ChevronUp,
  Code2,
  Contact,
  Copy,
  Cpu,
  Database,
  DollarSign,
  ExternalLink,
  HardDrive,
  Mail,
  Mic,
  Palette,
  RefreshCw,
  Search,
  Send,
  Settings2,
  Share2,
  Square,
  Target,
  Users,
  Volume2,
  VolumeX,
  Wallet,
  X,
  XCircle,
  type LucideIcon,
} from 'lucide-react';
import { getBase } from '../lib/api';
import { JarvisCore } from './JarvisCore';
import type { CoreState } from './JarvisCore';
import './one-cockpit.css';

type Agent = { id: string; name: string; role: string };

// Maps an agent's name/role to a representative icon, mirroring the labeled
// hub-and-spoke look (Strategist, Researcher, Sales, Ops, Design, CRM, ...)
// from the reference dashboard. Falls back to the agent's first initial
// when nothing matches, so unfamiliar/custom agent names never break.
const AGENT_ICON_RULES: Array<[RegExp, LucideIcon]> = [
  [/strateg/i, Target],
  [/research/i, Search],
  [/chief|staff|manager|coord/i, Users],
  [/sales|lead|revenue/i, DollarSign],
  [/finance|invoice|payment|billing/i, Wallet],
  [/ops|operation/i, Settings2],
  [/dev|engineer|build|code/i, Code2],
  [/analy|data|metric/i, BarChart3],
  [/social|content|market/i, Share2],
  [/crm|contact|client/i, Contact],
  [/design|brand|creative/i, Palette],
  [/calendar|schedule/i, RefreshCw],
  [/drive|file|storage|doc/i, HardDrive],
  [/mail|inbox|email/i, Mail],
  [/memory|recall|note/i, BrainCircuit],
  [/engineering|system|infra/i, Cpu],
];

function agentIcon(agent: Agent): LucideIcon | null {
  const haystack = `${agent.name} ${agent.role}`;
  for (const [pattern, Icon] of AGENT_ICON_RULES) {
    if (pattern.test(haystack)) return Icon;
  }
  return null;
}
type Job = { id: string; agent_id: string; task: string; mode: string; status: string; progress: number; result?: string; error?: string };
type Memory = { title: string; path: string; updated: string; preview: string };
type MemoryGraphNode = {
  id: string;
  title: string;
  path: string;
  kind: 'folder' | 'note' | 'conversation';
  updated: string;
  preview: string;
  weight: number;
};
type MemoryGraphEdge = { source: string; target: string; kind: string };
type MemoryGraph = {
  nodes: MemoryGraphNode[];
  edges: MemoryGraphEdge[];
  connected: boolean;
  vault_notes: number;
};
type Opportunity = {
  url: string;
  source: string;
  title: string;
  service: string;
  score: number;
  budget_min: number;
  budget_max: number;
  currency: string;
  service_definition: string;
  build_steps: string[];
  one_time_price: number;
  retainer_price: number;
  retainer_pitch: string;
  outreach_message: string;
  approval_status: 'pending_review' | 'approved' | 'dismissed';
  pipeline_stage?: string;
  client_name?: string;
  client_contact?: string;
  contact_channel?: string;
  response_status?: string;
  proposal_path?: string;
  agreement_path?: string;
  invoice_path?: string;
  payment_status?: string;
  amount_paid?: number;
  payment_reference?: string;
  delivery_status?: string;
};
type RevenueSummary = {
  potential_pipeline: number;
  potential_mrr: number;
  earned_revenue: number;
  active_mrr: number;
  paid_deals: number;
  open_deals: number;
};
type JobhuntApplication = {
  opportunity_id: string;
  date_found: string;
  source: string;
  company: string;
  role: string;
  location: string;
  job_url: string;
  posted_date: string;
  fit_score: string;
  status: string;
  resume_version: string;
  email_status: string;
  applied_status: string;
  next_action: string;
  last_touched: string;
  notes: string;
  brief_path: string;
  resume_notes_path: string;
};
type JobhuntBoard = {
  summary: {
    tracked: number;
    visible: number;
    draft_ready: number;
    email_drafts_ready: number;
    not_applied: number;
    tracker_csv: string;
    inbox: string;
    latest_scan?: Record<string, unknown>;
  };
  status_counts: Record<string, number>;
  email_counts: Record<string, number>;
  applied_counts: Record<string, number>;
  applications: JobhuntApplication[];
};
type ModelRoute = { scope: string; model: string; engine: string };
type ModelStatus = {
  engine: string;
  router_model: string;
  agent: string;
  nemotron_model: string;
  nemotron_ready: boolean;
  nvidia: { host: string; api_key_configured: boolean };
  route_map: ModelRoute[];
};
type OneStatus = {
  online: boolean;
  model: string;
  model_status?: ModelStatus;
  agents: Agent[];
  jobs: Job[];
  obsidian: { connected: boolean; path: string; notes: number };
  memories: Memory[];
};
type Line = { role: 'one' | 'user'; text: string };
type AudioDevice = { deviceId: string; label: string };
type WakeEvent = { id: number; created_at: string; transcript: string; recognized: number; summary: string };
type CredentialVaultEntry = {
  section: string;
  key: string;
  configured: boolean;
  active: boolean;
  deletable: boolean;
  masked: string;
};
type CredentialVault = {
  path: string;
  exists: boolean;
  count: number;
  entries: CredentialVaultEntry[];
};
type ConnectionPreset = {
  id: string;
  label: string;
  section: string;
  keys: string[];
  note: string;
};

const coreUrl = (path: string) => `${getBase()}${path}`;
const coreFetch = (path: string, init?: RequestInit) => fetch(coreUrl(path), init);

function normalizeSpeechText(text: string) {
  return text.toLowerCase().replace(/[^a-z0-9\s]/g, ' ').replace(/\s+/g, ' ').trim();
}

function isClearOneCommand(text: string) {
  const normalized = normalizeSpeechText(text);
  if (!normalized) return false;
  if (/\b(wake up one|hey one|hi one|hello one|one|jarvis)\b/.test(normalized)) return true;
  if (/\b(run|activate|start|open|search|scan|find|show|summarize|tell|stop|pause)\b/.test(normalized)
    && /\b(titan|alfa|alpha|athena|obsidian|memory|agent|lead|postforge)\b/.test(normalized)) return true;
  return false;
}

const DEFAULT_STATUS: OneStatus = {
  online: false,
  model: 'qwen3.5:2b',
  model_status: undefined,
  agents: [],
  jobs: [],
  obsidian: { connected: false, path: '', notes: 0 },
  memories: [],
};

const DEFAULT_CREDENTIAL_VAULT: CredentialVault = {
  path: '',
  exists: false,
  count: 0,
  entries: [],
};

const CONNECTION_PRESETS: ConnectionPreset[] = [
  { id: 'gmail', label: 'Gmail', section: 'gmail', keys: ['GMAIL_ADDRESS', 'GMAIL_APP_PASSWORD', 'GMAIL_CLIENT_ID', 'GMAIL_CLIENT_SECRET', 'GMAIL_REFRESH_TOKEN'], note: 'Jobhunt drafts, outbound mail, inbox workflows' },
  { id: 'whatsapp', label: 'WhatsApp', section: 'whatsapp', keys: ['WHATSAPP_ACCESS_TOKEN', 'WHATSAPP_PHONE_NUMBER_ID'], note: 'Message and lead workflows' },
  { id: 'instagram', label: 'Instagram', section: 'instagram_post', keys: ['INSTAGRAM_ACCESS_TOKEN', 'INSTAGRAM_BUSINESS_ACCOUNT_ID'], note: 'IA/PostForge publishing' },
  { id: 'facebook', label: 'Facebook', section: 'facebook_post', keys: ['FACEBOOK_PAGE_ACCESS_TOKEN', 'FACEBOOK_PAGE_ID'], note: 'Page publishing' },
  { id: 'openai', label: 'OpenAI', section: 'image_generate', keys: ['OPENAI_API_KEY'], note: 'Image generation fallback' },
  { id: 'fal', label: 'fal.ai', section: 'video_generate', keys: ['FAL_KEY'], note: 'Video/lip-sync pipeline' },
  { id: 'nvidia', label: 'NVIDIA', section: 'custom', keys: ['NVIDIA_API_KEY', 'NEMOTRON_MODEL'], note: 'Nemotron reasoning route' },
  { id: 'huggingface', label: 'Hugging Face', section: 'custom', keys: ['HF_TOKEN', 'HUGGINGFACE_HUB_TOKEN'], note: 'Local FLUX gated models' },
  { id: 'elevenlabs', label: 'ElevenLabs', section: 'custom', keys: ['ELEVENLABS_API_KEY'], note: 'Voice generation' },
  { id: 'leonardo', label: 'Leonardo', section: 'leonardo_video_generate', keys: ['LEONARDO_API_KEY'], note: 'IA image/video provider' },
];

export function OneCockpit() {
  const [status, setStatus] = useState<OneStatus>(DEFAULT_STATUS);
  const [command, setCommand] = useState('');
  const [lines, setLines] = useState<Line[]>([
    { role: 'one', text: 'ONE command core ready. Speak or type a command.' },
  ]);
  const [busy, setBusy] = useState(false);
  const [recording, setRecording] = useState(false);
  const [nativeRecording, setNativeRecording] = useState(false);
  const [transcribing, setTranscribing] = useState(false);
  const [voiceEnabled, setVoiceEnabled] = useState(true);
  const [memoryOpen, setMemoryOpen] = useState(false);
  const [vaultPath, setVaultPath] = useState('');
  const [memoryMessage, setMemoryMessage] = useState('');
  const [memoryFlash, setMemoryFlash] = useState(false);
  const [memoryGraph, setMemoryGraph] = useState<MemoryGraph>({ nodes: [], edges: [], connected: false, vault_notes: 0 });
  const [selectedMemory, setSelectedMemory] = useState<MemoryGraphNode | null>(null);
  const [audioDevices, setAudioDevices] = useState<AudioDevice[]>([]);
  const [selectedDeviceId, setSelectedDeviceId] = useState(() => window.localStorage.getItem('one-microphone') || '');
  const [micLevel, setMicLevel] = useState(0);
  const [micError, setMicError] = useState('');
  const recorderRef = useRef<MediaRecorder | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const audioContextRef = useRef<AudioContext | null>(null);
  const meterFrameRef = useRef<number | null>(null);
  const lastWakeEventRef = useRef<number | null>(null);
  const oneVoiceRef = useRef<SpeechSynthesisVoice | null>(null);
  const voiceLockedRef = useRef(false);
  const speechQueueRef = useRef<string[]>([]);
  const speechActiveRef = useRef(false);
  const spokenEchoRef = useRef<string[]>([]);
  const lastSpeechEndedAtRef = useRef(0);
  const [speaking, setSpeaking] = useState(false);
  // Drawer stays hidden on the orb screen, but opens directly into the
  // tracking dashboard when the user taps Agents & Results.
  const [drawerOpen, setDrawerOpen] = useState(false);
  // Always-listening mode: a continuous mic loop that replaces click-to-talk
  // until the user explicitly turns it off. Refs mirror the state so the
  // async loop (which runs outside the normal render cycle) always reads
  // live values instead of a stale closure.
  const [alwaysListening, setAlwaysListening] = useState(false);
  const alwaysListeningRef = useRef(false);
  const busyRef = useRef(false);
  const speakingRef = useRef(false);
  useEffect(() => { busyRef.current = busy; }, [busy]);
  useEffect(() => { speakingRef.current = speaking; }, [speaking]);
  useEffect(() => () => { alwaysListeningRef.current = false; }, []);
  // Holographic orb interaction: a 3D tilt that follows the cursor/finger,
  // and a trail of sparkle particles spawned wherever the orb is touched,
  // so it reads as a live hologram rather than a flat glowing circle.
  const orbRef = useRef<HTMLDivElement | null>(null);
  const [orbTilt, setOrbTilt] = useState({ x: 0, y: 0 });
  const [sparkles, setSparkles] = useState<Array<{ id: number; x: number; y: number; hue: number }>>([]);
  const sparkleSeq = useRef(0);
  const lastSparkleAt = useRef(0);

  const spawnSparkle = useCallback((clientX: number, clientY: number) => {
    const node = orbRef.current;
    if (!node) return;
    const rect = node.getBoundingClientRect();
    const x = ((clientX - rect.left) / rect.width) * 100;
    const y = ((clientY - rect.top) / rect.height) * 100;
    const id = sparkleSeq.current++;
    const hue = Math.random() > 0.45 ? 195 : 42;
    setSparkles((current) => [...current.slice(-22), { id, x, y, hue }]);
    window.setTimeout(() => setSparkles((current) => current.filter((sparkle) => sparkle.id !== id)), 760);
  }, []);

  const handleOrbPointerMove = useCallback((event: ReactPointerEvent<HTMLDivElement>) => {
    const node = orbRef.current;
    if (!node) return;
    const rect = node.getBoundingClientRect();
    const px = (event.clientX - rect.left) / rect.width - 0.5;
    const py = (event.clientY - rect.top) / rect.height - 0.5;
    setOrbTilt({ x: py * -22, y: px * 22 });
    const now = performance.now();
    if (now - lastSparkleAt.current > 55) {
      lastSparkleAt.current = now;
      spawnSparkle(event.clientX, event.clientY);
    }
  }, [spawnSparkle]);

  const handleOrbPointerLeave = useCallback(() => {
    setOrbTilt({ x: 0, y: 0 });
  }, []);

  const handleOrbPointerDown = useCallback((event: ReactPointerEvent<HTMLDivElement>) => {
    for (let i = 0; i < 8; i += 1) {
      const angle = (Math.PI * 2 * i) / 8;
      spawnSparkle(event.clientX + Math.cos(angle) * 14, event.clientY + Math.sin(angle) * 14);
    }
  }, [spawnSparkle]);

  const [alfaOpportunities, setAlfaOpportunities] = useState<Opportunity[]>([]);
  const [alfaExpanded, setAlfaExpanded] = useState<string | null>(null);
  const [alfaActionUrl, setAlfaActionUrl] = useState<string | null>(null);
  const [alfaCopiedUrl, setAlfaCopiedUrl] = useState<string | null>(null);
  const [alfaMessage, setAlfaMessage] = useState('');
  const [alfaSummary, setAlfaSummary] = useState<RevenueSummary>({ potential_pipeline: 0, potential_mrr: 0, earned_revenue: 0, active_mrr: 0, paid_deals: 0, open_deals: 0 });
  const [alfaForm, setAlfaForm] = useState({ clientName: '', clientContact: '', channel: 'Reddit DM', response: '', amount: '', reference: '' });
  const [jobhuntBoard, setJobhuntBoard] = useState<JobhuntBoard>({
    summary: { tracked: 0, visible: 0, draft_ready: 0, email_drafts_ready: 0, not_applied: 0, tracker_csv: '', inbox: '' },
    status_counts: {},
    email_counts: {},
    applied_counts: {},
    applications: [],
  });
  const [credentialVault, setCredentialVault] = useState<CredentialVault>(DEFAULT_CREDENTIAL_VAULT);
  const [credentialVaultMessage, setCredentialVaultMessage] = useState('');
  const [credentialActionKey, setCredentialActionKey] = useState<string | null>(null);
  const [selectedConnectionId, setSelectedConnectionId] = useState(CONNECTION_PRESETS[0].id);
  const selectedConnection = CONNECTION_PRESETS.find((preset) => preset.id === selectedConnectionId) || CONNECTION_PRESETS[0];
  const [credentialForm, setCredentialForm] = useState({ section: selectedConnection.section, key: selectedConnection.keys[0], value: '' });
  // The orb stage is fixed full-viewport and the results drawer is its own
  // fixed, internally-scrolling overlay, so the page itself never needs to
  // scroll. No overflow override needed here anymore.

  const refreshAlfaOpportunities = useCallback(async () => {
    try {
      const response = await coreFetch('/v1/alfa/pipeline?limit=50', { cache: 'no-store' });
      if (!response.ok) throw new Error('offline');
      const data = await response.json();
      setAlfaOpportunities(data.opportunities || []);
      if (data.summary) setAlfaSummary(data.summary);
    } catch {
      // ALFA's table may not exist yet (no scan has run); leave the list as-is.
    }
  }, []);

  useEffect(() => {
    void refreshAlfaOpportunities();
    const timer = window.setInterval(refreshAlfaOpportunities, 8000);
    return () => window.clearInterval(timer);
  }, [refreshAlfaOpportunities]);

  const refreshJobhuntBoard = useCallback(async () => {
    try {
      const response = await coreFetch('/v1/jobhunt/board?limit=50', { cache: 'no-store' });
      if (!response.ok) throw new Error('offline');
      const data = await response.json();
      setJobhuntBoard(data);
    } catch {
      setJobhuntBoard((current) => current);
    }
  }, []);

  useEffect(() => {
    void refreshJobhuntBoard();
    const timer = window.setInterval(refreshJobhuntBoard, 8000);
    return () => window.clearInterval(timer);
  }, [refreshJobhuntBoard]);

  const refreshCredentialVault = useCallback(async () => {
    try {
      const response = await coreFetch('/v1/one/credential-vault', { cache: 'no-store' });
      if (!response.ok) throw new Error('offline');
      const data = await response.json();
      setCredentialVault({
        path: data.path || '',
        exists: Boolean(data.exists),
        count: Number(data.count || 0),
        entries: data.entries || [],
      });
    } catch {
      setCredentialVault((current) => ({ ...current, exists: false }));
    }
  }, []);

  useEffect(() => {
    void refreshCredentialVault();
    const timer = window.setInterval(refreshCredentialVault, 10000);
    return () => window.clearInterval(timer);
  }, [refreshCredentialVault]);

  async function deleteVaultCredential(entry: CredentialVaultEntry) {
    setCredentialActionKey(entry.key);
    setCredentialVaultMessage('');
    try {
      const response = await coreFetch(`/v1/one/credential-vault/${encodeURIComponent(entry.section)}/${encodeURIComponent(entry.key)}`, { method: 'DELETE' });
      if (!response.ok) throw new Error('Delete failed');
      setCredentialVaultMessage(`${entry.key} removed from vault and cleared from the current ONE process.`);
      await refreshCredentialVault();
    } catch (error) {
      setCredentialVaultMessage(error instanceof Error ? error.message : 'Delete failed.');
    } finally {
      setCredentialActionKey(null);
    }
  }

  async function saveVaultCredential() {
    const section = credentialForm.section.trim() || selectedConnection.section || 'custom';
    const key = credentialForm.key.trim().toUpperCase();
    const value = credentialForm.value.trim();
    if (!key || !value) {
      setCredentialVaultMessage('Credential key and value are required.');
      return;
    }
    setCredentialActionKey(key);
    setCredentialVaultMessage('');
    try {
      const response = await coreFetch('/v1/one/credential-vault', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ section, key, value }),
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(payload.detail || 'Save failed');
      setCredentialForm((current) => ({ ...current, key, value: '' }));
      setCredentialVaultMessage(`${key} saved under ${section} and loaded in the current ONE process.`);
      await refreshCredentialVault();
    } catch (error) {
      setCredentialVaultMessage(error instanceof Error ? error.message : 'Save failed.');
    } finally {
      setCredentialActionKey(null);
    }
  }

  function editVaultCredential(entry: CredentialVaultEntry) {
    setSelectedConnectionId(CONNECTION_PRESETS.find((preset) => preset.section === entry.section && preset.keys.includes(entry.key))?.id || selectedConnectionId);
    setCredentialForm({ section: entry.section, key: entry.key, value: '' });
    setCredentialVaultMessage(`Enter a new value for ${entry.key}. Existing secret stays hidden.`);
  }

  function pickConnection(preset: ConnectionPreset) {
    setSelectedConnectionId(preset.id);
    setCredentialForm({ section: preset.section, key: preset.keys[0], value: '' });
    setCredentialVaultMessage('');
  }


  async function approveOpportunity(url: string) {
    setAlfaActionUrl(url);
    setAlfaMessage('');
    try {
      const response = await coreFetch('/v1/alfa/approve', {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ url }),
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.detail || 'Approval failed');
      setAlfaMessage('Outreach approved. Nothing was sent automatically; send the reviewed draft, then mark it contacted.');
      void refreshAlfaOpportunities();
      void refreshStatus();
    } catch (error) {
      setAlfaMessage(error instanceof Error ? error.message : 'Approval failed.');
    } finally {
      setAlfaActionUrl(null);
    }
  }

  async function dismissOpportunity(url: string) {
    setAlfaActionUrl(url);
    setAlfaMessage('');
    try {
      const response = await coreFetch('/v1/alfa/dismiss', {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ url }),
      });
      if (!response.ok) {
        const payload = await response.json();
        throw new Error(payload.detail || 'Dismiss failed');
      }
      setAlfaOpportunities((current) => current.filter((item) => item.url !== url));
    } catch (error) {
      setAlfaMessage(error instanceof Error ? error.message : 'Dismiss failed.');
    } finally {
      setAlfaActionUrl(null);
    }
  }

  async function copyOutreach(url: string, text: string) {
    try {
      await navigator.clipboard.writeText(text);
      setAlfaCopiedUrl(url);
      window.setTimeout(() => setAlfaCopiedUrl((current) => (current === url ? null : current)), 1800);
    } catch {
      setAlfaMessage('Could not copy to clipboard - select and copy the draft manually.');
    }
  }

  async function alfaAction(path: string, body: Record<string, unknown>, success: string) {
    setAlfaActionUrl(String(body.url || ''));
    setAlfaMessage('');
    try {
      const response = await coreFetch(`/v1/alfa/${path}`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.detail || 'Action failed');
      setAlfaMessage(success);
      setAlfaForm({ clientName: '', clientContact: '', channel: 'Reddit DM', response: '', amount: '', reference: '' });
      void refreshAlfaOpportunities();
      void refreshStatus();
    } catch (error) {
      setAlfaMessage(error instanceof Error ? error.message : 'Action failed.');
    } finally {
      setAlfaActionUrl(null);
    }
  }

  const refreshStatus = useCallback(async () => {
    try {
      const response = await coreFetch('/v1/one/status', { cache: 'no-store' });
      if (!response.ok) throw new Error('offline');
      const data = await response.json();
      setStatus(data);
      if (data.obsidian?.path) setVaultPath(data.obsidian.path);
    } catch {
      setStatus((current) => ({ ...current, online: false }));
    }
  }, []);

  const refreshMemoryGraph = useCallback(async () => {
    try {
      const response = await coreFetch('/v1/one/memory-graph?limit=95', { cache: 'no-store' });
      if (!response.ok) throw new Error('offline');
      const data = await response.json();
      setMemoryGraph({
        nodes: data.nodes || [],
        edges: data.edges || [],
        connected: Boolean(data.connected),
        vault_notes: Number(data.vault_notes || 0),
      });
    } catch {
      setMemoryGraph((current) => ({ ...current, connected: false }));
    }
  }, []);

  useEffect(() => {
    refreshStatus();
    const timer = window.setInterval(refreshStatus, 3000);
    return () => window.clearInterval(timer);
  }, [refreshStatus]);

  useEffect(() => {
    void refreshMemoryGraph();
    const timer = window.setInterval(refreshMemoryGraph, 12000);
    return () => window.clearInterval(timer);
  }, [refreshMemoryGraph]);

  useEffect(() => () => {
    streamRef.current?.getTracks().forEach((track) => track.stop());
    if (meterFrameRef.current) window.cancelAnimationFrame(meterFrameRef.current);
    void audioContextRef.current?.close();
    window.speechSynthesis?.cancel();
  }, []);

  const refreshAudioDevices = useCallback(async () => {
    const browserDevices = navigator.mediaDevices?.enumerateDevices
      ? (await navigator.mediaDevices.enumerateDevices())
        .filter((device) => device.kind === 'audioinput')
        .map((device, index) => ({ deviceId: device.deviceId, label: `Browser: ${device.label || `Microphone ${index + 1}`}` }))
      : [];
    let nativeDevices: AudioDevice[] = [];
    let nativeDefault = '';
    try {
      const response = await coreFetch('/v1/speech/devices', { cache: 'no-store' });
      const payload = await response.json();
      nativeDevices = (payload.devices || []).map((device: { index: number; name: string; host_api?: string }) => ({
        deviceId: `native:${device.index}`,
        label: `Windows: ${device.name}${device.host_api ? ` (${device.host_api.replace('Windows ', '')})` : ''}`,
      }));
      nativeDefault = `native:${payload.default_device}`;
    } catch {
      // Browser capture remains available when native capture is unavailable.
    }
    // Keep browser capture as the default path. Native capture is useful as a
    // fallback, but on some Windows audio stacks PortAudio/WASAPI can fail even
    // when Chrome can record the same microphone correctly.
    const devices = [...browserDevices, ...nativeDevices];
    setAudioDevices(devices);
    if (selectedDeviceId && !devices.some((device) => device.deviceId === selectedDeviceId)) {
      setSelectedDeviceId('');
      window.localStorage.removeItem('one-microphone');
    }
  }, [selectedDeviceId]);

  useEffect(() => {
    void refreshAudioDevices();
    navigator.mediaDevices?.addEventListener?.('devicechange', refreshAudioDevices);
    return () => navigator.mediaDevices?.removeEventListener?.('devicechange', refreshAudioDevices);
  }, [refreshAudioDevices]);

  const lockOneVoice = useCallback(() => {
    if (!('speechSynthesis' in window) || voiceLockedRef.current) return;
    const voices = window.speechSynthesis.getVoices();
    if (!voices.length) return;
    const savedVoice = window.localStorage.getItem('one-voice-uri');
    const preferred = voices.find((voice) => voice.voiceURI === savedVoice)
      || voices.find((voice) => /microsoft ryan.*natural/i.test(voice.name))
      || voices.find((voice) => /microsoft (david|mark|guy)/i.test(voice.name))
      || voices.find((voice) => /google uk english male|daniel/i.test(voice.name))
      || voices.find((voice) => /^en[-_](in|gb|us)/i.test(voice.lang))
      || voices[0];
    oneVoiceRef.current = preferred;
    voiceLockedRef.current = true;
    window.localStorage.setItem('one-voice-uri', preferred.voiceURI);
  }, []);

  const playNextSpeech = useCallback(function playNextSpeech() {
    if (!voiceEnabled || !('speechSynthesis' in window) || speechActiveRef.current) return;
    lockOneVoice();
    if (!voiceLockedRef.current) return;
    const next = speechQueueRef.current.shift();
    if (!next) { setSpeaking(false); return; }
    const utterance = new SpeechSynthesisUtterance(next);
    utterance.voice = oneVoiceRef.current;
    utterance.lang = oneVoiceRef.current?.lang || 'en-IN';
    utterance.rate = 0.96;
    utterance.pitch = 0.72;
    utterance.volume = 1;
    speechActiveRef.current = true;
    // Heartbeat on the core orb is driven by real speech playback, not by a
    // generic "busy" flag -- it turns on the instant audio actually starts
    // and off the instant the queue genuinely empties, so the pulse always
    // matches when ONE is audibly talking.
    utterance.onstart = () => setSpeaking(true);
    const finish = () => {
      speechActiveRef.current = false;
      if (!speechQueueRef.current.length) {
        lastSpeechEndedAtRef.current = Date.now();
        setSpeaking(false);
      }
      window.setTimeout(playNextSpeech, 35);
    };
    utterance.onend = finish;
    utterance.onerror = finish;
    window.speechSynthesis.speak(utterance);
  }, [lockOneVoice, voiceEnabled]);

  useEffect(() => {
    if (!voiceEnabled) setSpeaking(false);
  }, [voiceEnabled]);

  useEffect(() => {
    if (!('speechSynthesis' in window)) return undefined;
    const onVoicesChanged = () => {
      lockOneVoice();
      playNextSpeech();
    };
    onVoicesChanged();
    window.speechSynthesis.addEventListener('voiceschanged', onVoicesChanged);
    const timer = window.setTimeout(onVoicesChanged, 500);
    return () => {
      window.clearTimeout(timer);
      window.speechSynthesis.removeEventListener('voiceschanged', onVoicesChanged);
    };
  }, [lockOneVoice, playNextSpeech]);

  function speak(text: string, interrupt = true) {
    if (!voiceEnabled || !('speechSynthesis' in window)) return;
    const cleanText = text
      .replace(/[*_#`]/g, '')
      .replace(/[\u{1F000}-\u{1FAFF}\u{2600}-\u{27BF}\uFE0F]/gu, '')
      .replace(/\s+/g, ' ')
      .trim()
      .slice(0, 900);
    if (!cleanText) return;
    spokenEchoRef.current = [
      normalizeSpeechText(cleanText),
      ...spokenEchoRef.current,
    ].filter(Boolean).slice(0, 8);
    setSpeaking(true);
    if (interrupt) {
      window.speechSynthesis.cancel();
      speechQueueRef.current = [];
      speechActiveRef.current = false;
    }
    speechQueueRef.current.push(cleanText);
    playNextSpeech();
  }

  useEffect(() => {
    let cancelled = false;
    const pollWakeEvents = async () => {
      try {
        const response = await coreFetch('/v1/one/wake-events?limit=3', { cache: 'no-store' });
        const payload = await response.json();
        const events = (payload.events || []) as WakeEvent[];
        const latest = events[0];
        if (!latest || cancelled) return;
        if (lastWakeEventRef.current === null) {
          lastWakeEventRef.current = latest.id;
          const age = Date.now() - new Date(latest.created_at).getTime();
          if (latest.recognized && age < 15000) {
            setLines((current) => [...current.slice(-7), { role: 'one', text: latest.summary }]);
            speak(latest.summary);
          }
          return;
        }
        if (latest.id > lastWakeEventRef.current) {
          lastWakeEventRef.current = latest.id;
          if (latest.recognized) {
            setLines((current) => [...current.slice(-7), { role: 'one', text: latest.summary }]);
            speak(latest.summary);
          }
        }
      } catch {
        // Wake listener may still be starting.
      }
    };
    void pollWakeEvents();
    const timer = window.setInterval(pollWakeEvents, 1500);
    return () => { cancelled = true; window.clearInterval(timer); };
  }, [voiceEnabled]);

  const sendCommand = useCallback(async (raw?: string) => {
    const text = (raw ?? command).trim();
    if (!text || busy) return;
    setCommand('');
    setBusy(true);
    setLines((current) => [...current.slice(-6), { role: 'user', text }, { role: 'one', text: '' }]);
    try {
      const response = await coreFetch('/v1/chat/completions', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          model: status.model || 'qwen3.5:2b',
          messages: [{ role: 'user', content: text }],
          stream: true,
          temperature: 0.25,
          max_tokens: 220,
        }),
      });
      if (!response.ok) {
        // Server may return plain-text or HTML on crash (not JSON) — handle both
        let errorMsg = `ONE backend error (${response.status}). Make sure Ollama is running.`;
        try {
          const payload = await response.json();
          errorMsg = payload.detail || payload.error || errorMsg;
        } catch {
          const raw = await response.text().catch(() => '');
          if (raw.trim()) errorMsg = raw.slice(0, 200).replace(/\s+/g, ' ');
        }
        throw new Error(errorMsg);
      }

      const reader = response.body?.getReader();
      if (!reader) throw new Error('ONE could not open the response stream.');
      const decoder = new TextDecoder();
      let streamBuffer = '';
      let reply = '';
      let spokenChars = 0;

      const appendToken = (token: string) => {
        if (!token) return;
        reply += token;
        setLines((current) => {
          const next = [...current];
          if (next[next.length - 1]?.role === 'one') next[next.length - 1] = { role: 'one', text: reply };
          return next;
        });
        const pending = reply.slice(spokenChars);
        const sentence = pending.match(/^([\s\S]+?[.!?])(?:\s|$)/)?.[1]?.trim();
        if (sentence && sentence.length >= 18) {
          speak(sentence, spokenChars === 0);
          spokenChars += pending.indexOf(sentence) + sentence.length;
        } else if (pending.length >= 58) {
          const splitAt = pending.lastIndexOf(' ', 58);
          if (splitAt > 30) {
            const phrase = pending.slice(0, splitAt).trim();
            speak(phrase, spokenChars === 0);
            spokenChars += splitAt;
          }
        }
      };

      while (true) {
        const { value, done } = await reader.read();
        streamBuffer += decoder.decode(value || new Uint8Array(), { stream: !done });
        const frames = streamBuffer.split('\n\n');
        streamBuffer = frames.pop() || '';
        for (const frame of frames) {
          for (const line of frame.split('\n')) {
            if (!line.startsWith('data:')) continue;
            const data = line.slice(5).trim();
            if (!data || data === '[DONE]') continue;
            try {
              const payload = JSON.parse(data);
              appendToken(String(payload.choices?.[0]?.delta?.content || ''));
            } catch {
              // Ignore malformed partial SSE frames; the next frame continues.
            }
          }
        }
        if (done) break;
      }
      if (!reply.trim()) reply = 'Command received.';
      const remainder = reply.slice(spokenChars).trim();
      if (remainder) speak(remainder, spokenChars === 0);
      setLines((current) => {
        const next = [...current];
        if (next[next.length - 1]?.role === 'one') next[next.length - 1] = { role: 'one', text: reply };
        return next;
      });
      if (status.obsidian.connected) {
        void coreFetch('/v1/one/memory', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ command: text, response: reply }),
        }).then((memoryResponse) => memoryResponse.json()).then((memory) => {
          if (memory.saved) {
            setMemoryFlash(true);
            void refreshMemoryGraph();
            window.setTimeout(() => setMemoryFlash(false), 1800);
          }
        }).catch(() => undefined);
      }
      void refreshStatus();
    } catch (error) {
      const message = error instanceof Error ? error.message : 'ONE is offline.';
      setLines((current) => {
        const next = [...current];
        if (next[next.length - 1]?.role === 'one') next[next.length - 1] = { role: 'one', text: message };
        else next.push({ role: 'one', text: message });
        return next;
      });
    } finally {
      setBusy(false);
    }
  }, [busy, command, refreshMemoryGraph, refreshStatus, status.model, status.obsidian.connected, voiceEnabled]);

  async function transcribe(blob: Blob) {
    setTranscribing(true);
    try {
      const form = new FormData();
      form.append('file', blob, 'one-command.webm');
      const response = await coreFetch('/v1/speech/transcribe', { method: 'POST', body: form });
      if (!response.ok) {
        let errorMsg = 'Local speech recognition is unavailable';
        try { const p = await response.json(); errorMsg = p.detail || errorMsg; } catch { /* non-JSON error */ }
        throw new Error(errorMsg);
      }
      const payload = await response.json();
      const text = String(payload.text || '').trim();
      if (!text) throw new Error('I could not hear a clear command.');
      // No wake-word gate here: the user explicitly pressed the mic button,
      // so send whatever they said directly to ONE.
      setCommand(text);
      await sendCommand(text.replace(/^\s*(hey\s+)?one[,:]?\s*/i, ''));
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Transcription failed.';
      setLines((current) => [...current.slice(-7), { role: 'one', text: message }]);
    } finally {
      setTranscribing(false);
    }
  }

  async function nativeRecord(deviceOverride?: number, opts?: { silent?: boolean }) {
    const silent = opts?.silent ?? false;
    setMicError('');
    setNativeRecording(true);
    setRecording(true);
    setMicLevel(55);
    try {
      const selected = selectedDeviceId.startsWith('native:') ? Number(selectedDeviceId.split(':')[1]) : undefined;
      const response = await coreFetch('/v1/speech/native-record', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ device: deviceOverride ?? selected, duration: silent ? 4 : 5 }),
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.detail || 'Native microphone capture failed.');
      const text = String(payload.text || '').trim();
      if (!text) {
        // In always-listening mode, most capture windows will be ambient
        // silence between commands -- that's expected, not an error worth
        // surfacing every few seconds.
        if (silent) return;
        const peak = Number(payload.max_peak || 0);
        throw new Error(peak < 0.015
          ? 'ONE received almost silent audio. Select the WASAPI microphone and speak closer to it.'
          : 'ONE heard sound but not clear speech. Speak after the listening light turns on.');
      }
      const normalized = normalizeSpeechText(text);
      const soundsLikeEcho = spokenEchoRef.current.some((spoken) => (
        spoken.length > 18
        && (spoken.includes(normalized) || normalized.includes(spoken.slice(0, 90)))
      ));
      if (silent && (soundsLikeEcho || !isClearOneCommand(text))) return;
      if (!silent && soundsLikeEcho) throw new Error('ONE heard its own voice. Try again after it finishes speaking.');
      setCommand(text);
      await sendCommand(text.replace(/^\s*(hey\s+)?one[,:]?\s*/i, ''));
    } catch (error) {
      if (silent) return;
      const message = error instanceof Error ? error.message : 'Native microphone capture failed.';
      setMicError(message);
      setLines((current) => [...current.slice(-7), { role: 'one', text: message }]);
    } finally {
      setRecording(false);
      setNativeRecording(false);
      setMicLevel(0);
    }
  }

  async function startRecording() {
    setMicError('');
    if (selectedDeviceId.startsWith('native:')) {
      await nativeRecord();
      return;
    }
    try {
      if (!navigator.mediaDevices?.getUserMedia) throw new DOMException('Audio capture is unavailable in this browser.', 'NotSupportedError');
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          ...(selectedDeviceId ? { deviceId: { exact: selectedDeviceId } } : {}),
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
          channelCount: 1,
        },
      });
      const track = stream.getAudioTracks()[0];
      if (!track || track.readyState !== 'live') throw new DOMException('The selected microphone is not producing a live track.', 'NotReadableError');
      streamRef.current = stream;
      chunksRef.current = [];
      await refreshAudioDevices();

      const AudioContextClass = window.AudioContext || (window as typeof window & { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
      if (AudioContextClass) {
        const context = new AudioContextClass();
        audioContextRef.current = context;
        const analyser = context.createAnalyser();
        analyser.fftSize = 256;
        context.createMediaStreamSource(stream).connect(analyser);
        const values = new Uint8Array(analyser.frequencyBinCount);
        const updateMeter = () => {
          analyser.getByteFrequencyData(values);
          const average = values.reduce((sum, value) => sum + value, 0) / values.length;
          setMicLevel(Math.min(100, Math.round(average * 1.8)));
          meterFrameRef.current = window.requestAnimationFrame(updateMeter);
        };
        updateMeter();
      }

      const mimeType = ['audio/webm;codecs=opus', 'audio/webm', 'audio/ogg;codecs=opus']
        .find((type) => MediaRecorder.isTypeSupported(type));
      const recorder = mimeType ? new MediaRecorder(stream, { mimeType }) : new MediaRecorder(stream);
      recorderRef.current = recorder;
      recorder.ondataavailable = (event) => {
        if (event.data.size) chunksRef.current.push(event.data);
      };
      recorder.onstop = () => {
        const audio = new Blob(chunksRef.current, { type: recorder.mimeType });
        stream.getTracks().forEach((track) => track.stop());
        streamRef.current = null;
        if (meterFrameRef.current) window.cancelAnimationFrame(meterFrameRef.current);
        meterFrameRef.current = null;
        setMicLevel(0);
        void audioContextRef.current?.close();
        audioContextRef.current = null;
        if (audio.size < 800) {
          setMicError('No usable audio was captured. Select another microphone and try again.');
          return;
        }
        void transcribe(audio);
      };
      recorder.onerror = () => setMicError('Chrome could not encode audio from this microphone. Select another input and retry.');
      recorder.start(250);
      setRecording(true);
    } catch (error) {
      const captureError = error as DOMException;
      if (captureError.name === 'NotAllowedError') {
        await nativeRecord();
        return;
      }
      const messages: Record<string, string> = {
        NotAllowedError: 'Chrome or Windows has denied microphone access.',
        NotFoundError: 'No microphone was found. Reconnect it and refresh devices.',
        NotReadableError: 'The microphone is busy or unavailable. Close other recording apps or select another device.',
        OverconstrainedError: 'The selected microphone is no longer available. Refresh devices and choose another input.',
        SecurityError: 'Microphone capture is blocked by browser security settings.',
        NotSupportedError: captureError.message || 'This browser cannot capture audio.',
      };
      const message = messages[captureError.name] || `${captureError.name || 'Microphone error'}: ${captureError.message || 'Unable to start recording.'}`;
      setMicError(message);
      setLines((current) => [...current.slice(-7), { role: 'one', text: message }]);
    }
  }

  function stopRecording() {
    if (recorderRef.current?.state === 'recording') recorderRef.current.stop();
    setRecording(false);
  }

  // Always-listening mode: instead of click-to-talk, ONE keeps capturing
  // short windows from the microphone back-to-back -- pausing only while
  // it's thinking or speaking, so it doesn't pick up its own voice -- until
  // the user explicitly turns it off again.
  async function runListenLoop() {
    while (alwaysListeningRef.current) {
      while (
        alwaysListeningRef.current
        && (speakingRef.current || busyRef.current || Date.now() - lastSpeechEndedAtRef.current < 1500)
      ) {
        await new Promise((resolve) => window.setTimeout(resolve, 250));
      }
      if (!alwaysListeningRef.current) break;
      try {
        await nativeRecord(undefined, { silent: true });
      } catch {
        // Always-listening tolerates noisy/empty windows silently.
      }
      if (!alwaysListeningRef.current) break;
      await new Promise((resolve) => window.setTimeout(resolve, 350));
    }
  }

  function toggleAlwaysListening() {
    if (alwaysListeningRef.current) {
      alwaysListeningRef.current = false;
      setAlwaysListening(false);
      if (recorderRef.current?.state === 'recording') stopRecording();
      return;
    }
    alwaysListeningRef.current = true;
    setAlwaysListening(true);
    void runListenLoop();
  }

  function chooseAudioDevice(deviceId: string) {
    setSelectedDeviceId(deviceId);
    if (deviceId) window.localStorage.setItem('one-microphone', deviceId);
    else window.localStorage.removeItem('one-microphone');
    setMicError('');
  }

  async function connectObsidian() {
    setMemoryMessage('Connecting...');
    try {
      const response = await coreFetch('/v1/one/obsidian', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ path: vaultPath }),
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.detail || 'Connection failed');
      setMemoryMessage(`${payload.notes} notes connected locally.`);
      await refreshStatus();
    } catch (error) {
      setMemoryMessage(error instanceof Error ? error.message : 'Connection failed');
    }
  }

  const activeJobs = status.jobs.filter((job) => job.status === 'queued' || job.status === 'running');
  const latestJobs = status.jobs.slice(0, 5);
  const modelStatus = status.model_status;
  function alfaResult(job: Job) {
    if (job.agent_id !== 'alfa' || !job.result) return null;
    try {
      const result = JSON.parse(job.result);
      const mrr = Number(result.mrr_pipeline_monthly ?? 0);
      const mrrPart = mrr > 0 ? ` | $${mrr.toLocaleString()}/mo MRR pipeline` : '';
      return `${result.qualified ?? 0} leads | $${Number(result.estimated_usd_low ?? 0).toLocaleString()}-$${Number(result.estimated_usd_high ?? 0).toLocaleString()}${mrrPart}`;
    } catch {
      return null;
    }
  }
  const agentExecutionSections = useMemo(() => status.agents.map((agent) => ({
    agent,
    jobs: status.jobs.filter((job) => job.agent_id === agent.id).slice(0, 3),
  })).filter((section) => section.jobs.length), [status.agents, status.jobs]);
  function jobResult(job: Job) {
    if (job.agent_id === 'alfa') return alfaResult(job);
    if (!job.result) return null;
    try {
      const result = JSON.parse(job.result);
      if (job.agent_id === 'jobhunt') {
        return `${result.loaded ?? 0} reviewed | ${result.new_briefs ?? 0} new briefs | ${result.duplicates ?? 0} duplicates`;
      }
      if (result.mode) return String(result.mode).replace(/-/g, ' ');
      if (result.content) return String(result.content).slice(0, 120);
      return null;
    } catch {
      return null;
    }
  }
  const memoryUniverse = useMemo(() => {
    const center = 400;
    const hash = (value: string) => Array.from(value).reduce((total, character) => ((total * 31) + character.charCodeAt(0)) >>> 0, 7);
    const groups = {
      folder: memoryGraph.nodes.filter((node) => node.kind === 'folder'),
      note: memoryGraph.nodes.filter((node) => node.kind === 'note'),
      conversation: memoryGraph.nodes.filter((node) => node.kind === 'conversation'),
    };
    const radii = { folder: 126, note: 214, conversation: 286 };
    const positions = new Map<string, MemoryGraphNode & { x: number; y: number }>();
    (Object.keys(groups) as Array<keyof typeof groups>).forEach((kind, groupIndex) => {
      const nodes = groups[kind];
      nodes.forEach((node, index) => {
        const seed = hash(node.id);
        const angle = ((Math.PI * 2 * index) / Math.max(nodes.length, 1)) - Math.PI / 2 + groupIndex * 0.19;
        const radius = radii[kind] + ((seed % 25) - 12);
        positions.set(node.id, { ...node, x: center + Math.cos(angle) * radius, y: center + Math.sin(angle) * radius });
      });
    });
    const nodes = Array.from(positions.values());
    const edges = memoryGraph.edges.flatMap((edge) => {
      const source = positions.get(edge.source);
      const target = positions.get(edge.target);
      return source && target ? [{ ...edge, sourceNode: source, targetNode: target }] : [];
    });
    return { nodes, edges };
  }, [memoryGraph]);

  // Spoke endpoints for the agent nodes, in the same 0-100 percentage space
  // as their CSS placement (--angle = 360/count * index - 90deg, radius =
  // 50% of the orbit diameter) so the SVG connector lines land exactly on
  // each node's center regardless of viewport size.
  const agentSpokes = useMemo(() => {
    const count = status.agents.length;
    if (!count) return [];
    return status.agents.map((agent, index) => {
      const angle = ((360 / count) * index - 90) * (Math.PI / 180);
      return { agent, x: 50 + 50 * Math.cos(angle), y: 50 + 50 * Math.sin(angle) };
    });
  }, [status.agents]);

  const coreState: CoreState = !status.online
    ? 'offline'
    : recording
    ? 'listening'
    : speaking
    ? 'speaking'
    : busy || transcribing
    ? 'thinking'
    : 'awake';

  // Left-panel status rows
  const leftStats = [
    { label: 'SYSTEM', value: status.online ? 'NOMINAL' : 'OFFLINE', ok: status.online },
    { label: 'ALFA',   value: alfaOpportunities.length > 0 ? 'ACTIVE' : 'IDLE', ok: alfaOpportunities.length > 0 },
    ...status.agents.slice(0, 4).map(a => ({
      label: a.name.toUpperCase().slice(0, 6),
      value: 'READY',
      ok: true,
    })),
  ];

  // Last ONE reply shown on the landing screen (avoids IIFE inside JSX)
  const lastOneReply = [...lines].reverse().find(l => l.role === 'one' && l.text.trim());

  // Right-panel metric rows
  const rightMetrics = [
    { label: 'NEURAL',   value: `${Math.min(100, Math.round(status.obsidian.notes / 3))}%`, ok: status.online },
    { label: 'AGENTS',   value: `${status.agents.length} / ${status.agents.length}`,         ok: status.agents.length > 0 },
    { label: 'MEMORIES', value: `${status.obsidian.notes}`,                                  ok: status.online },
    { label: 'LISTEN',   value: alwaysListening ? 'ON' : 'OFF',                              ok: alwaysListening },
    { label: 'CORE',     value: status.online ? 'ONLINE' : 'OFFLINE',                        ok: status.online },
  ];

  return (
    <main className="one-shell one-focus-mode">
      <div className="one-grid" />

      <section className="one-focus-stage">
        {/* ── Top header ── */}
        <header className="jarvis-pg-header" aria-hidden="true">
          <div className="jarvis-pg-header-line" />
          <span>J · A · R · V · I · S &nbsp;&nbsp; I N T E R F A C E</span>
          <div className="jarvis-pg-header-line" />
        </header>

        {/* ── Three-column main ── */}
        <div className="jarvis-pg-main">
          {/* Left status panel */}
          <aside className="jarvis-pg-panel jarvis-pg-panel--left" aria-label="System status">
            {leftStats.map((item, i) => (
              <div key={i} className={`jarvis-pg-stat ${item.ok ? 'jarvis-pg-stat--ok' : 'jarvis-pg-stat--dim'}`}>
                <span className="jarvis-pg-dot" />
                {item.label} <strong>{item.value}</strong>
              </div>
            ))}
          </aside>

          {/* Centre orb */}
          <div className="jarvis-pg-orb-wrap">
            <div className="jarvis-pg-core-label" aria-hidden="true">LOCAL CORE</div>
            <JarvisCore
              state={coreState}
              memories={status.obsidian.notes}
              onTap={recording ? stopRecording : startRecording}
            />
          </div>

          {/* Right metrics panel */}
          <aside className="jarvis-pg-panel jarvis-pg-panel--right" aria-label="System metrics">
            {rightMetrics.map((item, i) => (
              <div key={i} className={`jarvis-pg-metric ${item.ok ? 'jarvis-pg-metric--ok' : 'jarvis-pg-metric--dim'}`}>
                <strong>{item.value}</strong> {item.label}
                <span className="jarvis-pg-dot" />
              </div>
            ))}
          </aside>
        </div>

        {/* ── Live response strip — shows ONE's last reply on the landing screen ── */}
        <div className="jarvis-live-output" aria-live="polite" aria-atomic="false">
          {transcribing && <div className="jarvis-live-status">◆ TRANSCRIBING...</div>}
          {busy && !transcribing && <div className="jarvis-live-status">◆ PROCESSING...</div>}
          {!busy && !transcribing && lastOneReply && (
            <p className="jarvis-live-reply">{lastOneReply.text}</p>
          )}
        </div>

        {/* ── Inline command bar ── */}
        <div className="jarvis-cmd-row">
          <button
            className={`jarvis-cmd-mic-btn${recording ? ' recording' : ''}`}
            onClick={recording ? stopRecording : startRecording}
            disabled={!status.online || transcribing || nativeRecording}
            title={recording ? 'Stop recording' : 'Tap to speak to ONE'}
          >
            {recording ? <Square size={15} fill="currentColor" /> : <Mic size={17} />}
          </button>
          <input
            className="jarvis-cmd-field"
            value={command}
            onChange={(e) => setCommand(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter') void sendCommand(); }}
            placeholder={status.online ? 'Ask ONE anything...' : 'Start ONE to continue'}
            disabled={!status.online || busy}
            autoComplete="off"
            spellCheck={false}
          />
          <button
            className="jarvis-cmd-go"
            onClick={() => void sendCommand()}
            disabled={!command.trim() || busy || !status.online}
            title="Send"
          >
            <Send size={15} />
          </button>
        </div>

        {/* ── Footer ── */}
        <footer className="jarvis-pg-footer">
          <div className="jarvis-pg-hint" aria-hidden="true">DRAG TO ROTATE · SCROLL TO ZOOM</div>
          <button
            type="button"
            className={`one-listen-toggle ${alwaysListening ? 'on' : ''}`}
            title={alwaysListening ? 'Stop continuous listening' : 'Listen continuously until I turn it off'}
            onClick={toggleAlwaysListening}
            disabled={!status.online}
          >
            {alwaysListening ? <Square size={16} fill="currentColor" /> : <Mic size={18} />}
            <span>{alwaysListening ? 'LISTENING - TAP TO STOP' : 'ALWAYS LISTEN'}</span>
          </button>
          {micError && <div className="one-mic-error">{micError}</div>}
        </footer>
      </section>

      <button
        type="button"
        className={`one-drawer-tab ${drawerOpen ? 'open' : ''}`}
        title={drawerOpen ? 'Hide tracking dashboard' : 'Open tracking dashboard'}
        onClick={() => setDrawerOpen((value) => !value)}
      >
        <ChevronUp size={16} />
        <span>{drawerOpen ? 'HIDE DASHBOARD' : 'TRACKING DASHBOARD'}</span>
      </button>

      <aside className={`one-results-drawer ${drawerOpen ? 'open' : ''}`} aria-hidden={!drawerOpen}>
        <header className="one-header">
          <div className="one-brand">
            <span className={`one-status-dot ${status.online ? 'online' : ''}`} />
            <div><strong>ONE</strong><span>{status.online ? 'LOCAL CORE ONLINE' : 'CORE OFFLINE'}</span></div>
          </div>
          <div className="one-header-actions">
            <span>CLAP + WAKE ARMED</span>
            <span>{activeJobs.length} ACTIVE</span>
            <span className={`one-brain-chip ${modelStatus?.nemotron_ready ? 'nemotron' : ''}`}>
              {(modelStatus?.engine || 'ollama').toUpperCase()} | {status.model}
            </span>
            <button title={voiceEnabled ? 'Mute ONE' : 'Enable ONE voice'} onClick={() => setVoiceEnabled((value) => !value)}>
              {voiceEnabled ? <Volume2 size={18} /> : <VolumeX size={18} />}
            </button>
            <button title="Connect memory" onClick={() => setMemoryOpen(true)}><Database size={18} /></button>
            <a title="Advanced system console" href="/?advanced=1"><Settings2 size={18} /></a>
          </div>
        </header>

        <section className="one-operations one-brain-board">
          <div className="one-operations-head">
            <div><div className="one-panel-label">ONE MODEL ROUTING</div><strong>ACTIVE BRAIN AND SPECIALIST BACKENDS</strong></div>
            <span className="one-alfa-mrr">
              {modelStatus?.nemotron_ready ? 'Nemotron ready' : 'Local/default brain'} | {modelStatus?.engine || 'ollama'}
            </span>
          </div>
          <div className="one-brain-grid">
            <div>
              <span>Router</span>
              <strong>{modelStatus?.router_model || status.model}</strong>
              <small>{modelStatus?.engine || 'ollama'} / {modelStatus?.agent || 'react'}</small>
            </div>
            <div>
              <span>Nemotron</span>
              <strong>{modelStatus?.nemotron_model || 'Not selected'}</strong>
              <small>{modelStatus?.nvidia?.api_key_configured ? modelStatus.nvidia.host : 'NVIDIA key not configured'}</small>
            </div>
            <div>
              <span>Media</span>
              <strong>gpt-image-1 + fal/Leonardo</strong>
              <small>IA tools stay separate from text brain</small>
            </div>
          </div>
          <div className="one-route-map">
            {(modelStatus?.route_map || []).map((route) => (
              <article key={route.scope}>
                <span>{route.scope.replace(/_/g, ' ')}</span>
                <strong>{route.model}</strong>
                <small>{route.engine}</small>
              </article>
            ))}
          </div>
        </section>

        <section className="one-operations one-credential-launcher">
          <div className="one-operations-head">
            <div><div className="one-panel-label">CREDENTIALS</div><strong>VAULT MANAGER</strong></div>
            <span className="one-alfa-mrr">{credentialVault.count} saved | values hidden</span>
          </div>
          <div className="one-credential-launch-card">
            <div>
              <Wallet size={16} />
              <span title={credentialVault.path}>{credentialVault.exists ? 'Local credential vault active' : 'Credential vault file not found'}</span>
            </div>
            <a href="/credentials" target="_blank" rel="noreferrer">
              <ExternalLink size={13} /> Open Vault
            </a>
          </div>
        </section>

        <section className="one-stage">
          <div className={`one-memory-universe ${memoryFlash ? 'memory-writing' : ''}`}>
            <div className="one-graph-summary">
              <span>LIVE MEMORY</span>
              <strong>{memoryUniverse.nodes.length} NODES</strong>
              <small>{memoryUniverse.edges.length} SYNAPSES</small>
            </div>
            <div className="one-graph-legend" aria-label="Memory graph legend">
              <span><i className="folder" />Areas</span>
              <span><i className="note" />Memories</span>
              <span><i className="conversation" />Conversations</span>
            </div>
            <svg className="one-neural-links" viewBox="0 0 800 800" role="img" aria-label="ONE connected Obsidian memory graph">
              <defs>
                <linearGradient id="one-synapse" x1="0" y1="0" x2="1" y2="1">
                  <stop offset="0" stopColor="#28d7ff" stopOpacity=".12" />
                  <stop offset=".5" stopColor="#6fe7ff" stopOpacity=".75" />
                  <stop offset="1" stopColor="#675cff" stopOpacity=".12" />
                </linearGradient>
                <radialGradient id="memory-node-glow">
                  <stop offset="0" stopColor="#dffcff" />
                  <stop offset=".4" stopColor="#58d8ff" />
                  <stop offset="1" stopColor="#126386" />
                </radialGradient>
              </defs>
              <circle className="memory-field outer" cx="400" cy="400" r="302" />
              <circle className="memory-field middle" cx="400" cy="400" r="222" />
              <circle className="memory-field inner" cx="400" cy="400" r="134" />
              {memoryUniverse.nodes.filter((node) => node.kind === 'folder').map((node) => (
                <line key={`core-${node.id}`} className="core-link" x1="400" y1="400" x2={node.x} y2={node.y} />
              ))}
              {memoryUniverse.edges.map((edge, index) => (
                <g key={`${edge.source}-${edge.target}-${index}`}>
                  <line className={`graph-edge ${edge.kind}`} x1={edge.sourceNode.x} y1={edge.sourceNode.y} x2={edge.targetNode.x} y2={edge.targetNode.y} />
                  {index < 18 && <circle className="memory-signal" r="2.4">
                    <animateMotion dur={`${3.4 + (index % 7) * .55}s`} repeatCount="indefinite" path={`M${edge.sourceNode.x},${edge.sourceNode.y} L${edge.targetNode.x},${edge.targetNode.y}`} />
                  </circle>}
                </g>
              ))}
              {memoryUniverse.nodes.map((node) => (
                <g
                  key={node.id}
                  className={`graph-node ${node.kind} ${selectedMemory?.id === node.id ? 'selected' : ''}`}
                  transform={`translate(${node.x} ${node.y})`}
                  onClick={() => {
                    setSelectedMemory(node);
                    setCommand(`Search my Obsidian for ${node.title}`);
                  }}
                  role="button"
                  tabIndex={0}
                >
                  <title>{`${node.title}\n${node.preview}`}</title>
                  <circle r={node.kind === 'folder' ? 7 : node.kind === 'note' ? 5 : 3.2} />
                  {(node.kind === 'folder' || (node.kind === 'note' && node.weight > 2)) && <text y="-10">{node.title.slice(0, 18)}</text>}
                </g>
              ))}
            </svg>
            <svg className="one-agent-links" viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true">
              <defs>
                <linearGradient id="one-spoke" x1="0" y1="0" x2="1" y2="1">
                  <stop offset="0" stopColor="#ffd166" stopOpacity=".05" />
                  <stop offset=".55" stopColor="#ffd166" stopOpacity=".5" />
                  <stop offset="1" stopColor="#58d8ff" stopOpacity=".75" />
                </linearGradient>
              </defs>
              {agentSpokes.map(({ agent, x, y }) => (
                <g key={agent.id}>
                  <line className="agent-spoke" x1="50" y1="50" x2={x} y2={y} vectorEffect="non-scaling-stroke" />
                  <circle className="agent-spoke-pulse" r="1.1" vectorEffect="non-scaling-stroke">
                    <animateMotion dur="2.6s" repeatCount="indefinite" path={`M50,50 L${x},${y}`} />
                  </circle>
                </g>
              ))}
            </svg>
            {status.agents.map((agent, index) => {
              const Icon = agentIcon(agent);
              return (
                <button
                  key={agent.id}
                  className="one-agent-node"
                  style={{ '--agent-index': index, '--agent-count': status.agents.length } as CSSProperties}
                  title={agent.role}
                  onClick={() => setCommand(`Activate ${agent.name} to plan `)}
                >
                  <span>{Icon ? <Icon size={18} strokeWidth={1.6} /> : agent.name.slice(0, 1)}</span>
                  <strong>{agent.name}</strong>
                </button>
              );
            })}
            {selectedMemory && (
              <div className="one-memory-inspector">
                <button title="Close memory detail" onClick={() => setSelectedMemory(null)}><X size={13} /></button>
                <span>{selectedMemory.kind}</span>
                <strong>{selectedMemory.title}</strong>
                <p>{selectedMemory.preview || selectedMemory.path}</p>
              </div>
            )}
            <div className={`one-memory-write ${memoryFlash ? 'visible' : ''}`}>MEMORY CONSOLIDATED</div>
          </div>

          <aside className="one-conversation" aria-live="polite">
            <div className="one-panel-label">LIVE CHANNEL</div>
            <div className="one-lines">
              {lines.map((line, index) => (
                <div className={`one-line ${line.role}`} key={`${line.role}-${index}`}>
                  <span>{line.role === 'one' ? 'ONE' : 'YOU'}</span>
                  <p>{line.text}</p>
                </div>
              ))}
            </div>
            <div className="one-mic-controls">
              <select value={selectedDeviceId} onChange={(event) => chooseAudioDevice(event.target.value)} aria-label="Microphone input">
                <option value="">Browser default microphone</option>
                {audioDevices.map((device) => <option key={device.deviceId} value={device.deviceId}>{device.label}</option>)}
              </select>
              <div className="one-level" title="Live microphone level"><i style={{ width: `${micLevel}%` }} /></div>
              <button title="Refresh microphone list" onClick={() => void refreshAudioDevices()}><RefreshCw size={14} /></button>
            </div>

            {/* Typing fallback. Always-listen mode handles voice on its
                own, so this lives tucked in the drawer instead of sitting
                in front of the orb. */}
            <div className="one-command-bar">
              <button
                className={`one-mic ${recording ? 'recording' : ''}`}
                title={recording ? 'Stop recording' : 'Speak to ONE'}
                onClick={recording ? stopRecording : startRecording}
                disabled={!status.online || transcribing || nativeRecording}
              >
                {recording ? <Square size={20} fill="currentColor" /> : <Mic size={22} />}
              </button>
              <input
                value={command}
                onChange={(event) => setCommand(event.target.value)}
                onKeyDown={(event) => { if (event.key === 'Enter') void sendCommand(); }}
                placeholder={status.online ? 'Or type a command...' : 'Start ONE to continue'}
                disabled={!status.online}
              />
              <button className="one-send" title="Send command" onClick={() => void sendCommand()} disabled={!command.trim() || busy}>
                <Send size={20} />
              </button>
            </div>
          </aside>
        </section>

        <section className="one-operations one-agent-operations">
        <div className="one-operations-head">
          <div><div className="one-panel-label">AGENT OPERATIONS</div><strong>NEURAL ACTIVITY</strong></div>
          <div className="one-memory-health"><Database size={16} /><span>{status.obsidian.notes} permanent memories</span><i className={status.obsidian.connected ? 'online' : ''} /></div>
        </div>
        <div className="one-job-strip">
          {!latestJobs.length && <p>No missions yet. Activate an agent by voice.</p>}
          {latestJobs.map((job) => (
            <article key={job.id} className={job.status}>
              <div><strong>{job.agent_id.toUpperCase()}</strong><span>{job.status}</span></div>
              <p>{job.task}</p>
              {jobResult(job) && <small className="one-alfa-result">{jobResult(job)}</small>}
              <div className="one-progress"><i style={{ width: `${job.progress}%` }} /></div>
              {job.error && <em>{job.error}</em>}
            </article>
          ))}
        </div>
        <div className="one-agent-execution-grid">
          {!agentExecutionSections.length && <p>No agent execution history yet.</p>}
          {agentExecutionSections.map(({ agent, jobs }) => (
            <article key={agent.id} className="one-agent-execution">
              <div className="one-agent-execution-head">
                <div>
                  <span>{agent.name}</span>
                  <strong>{agent.role}</strong>
                </div>
                <i className={jobs.some((job) => job.status === 'running' || job.status === 'queued') ? 'online' : ''} />
              </div>
              {jobs.map((job) => (
                <div key={job.id} className={`one-agent-run ${job.status}`}>
                  <div><strong>{job.mode}</strong><span>{job.status}</span></div>
                  <p>{job.task}</p>
                  {jobResult(job) && <small>{jobResult(job)}</small>}
                  {job.error && <em>{job.error}</em>}
                </div>
              ))}
            </article>
          ))}
        </div>
      </section>

      <section className="one-operations one-jobhunt-board">
        <div className="one-operations-head">
          <div><div className="one-panel-label">JOBHUNT APPLICATION PIPELINE</div><strong>QA / PRODUCT OWNER TRACTION BOARD</strong></div>
          <span className="one-alfa-mrr">{jobhuntBoard.summary.tracked} tracked | {jobhuntBoard.summary.draft_ready} ready for review</span>
        </div>
        <div className="one-revenue-summary one-jobhunt-summary">
          <div><span>Tracked roles</span><strong>{jobhuntBoard.summary.tracked.toLocaleString()}</strong></div>
          <div><span>Resume drafts</span><strong>{jobhuntBoard.summary.draft_ready.toLocaleString()}</strong></div>
          <div><span>Email drafts</span><strong>{jobhuntBoard.summary.email_drafts_ready.toLocaleString()}</strong></div>
          <div><span>Apply queue</span><strong>{jobhuntBoard.summary.not_applied.toLocaleString()}</strong></div>
        </div>
        <p className="one-jobhunt-note">
          Autonomous work: ingest alerts/JDs, review fit, create resume notes, prepare outreach, and record audit trail. Apply/send stays review-gated for account safety.
        </p>
        <div className="one-jobhunt-list">
          {!jobhuntBoard.applications.length && <p>No applications tracked yet. Add LinkedIn/Naukri/Gmail alert text into the JOBHUNT inbox, then run JOBHUNT.</p>}
          {jobhuntBoard.applications.map((item) => (
            <article key={item.opportunity_id} className="one-jobhunt-card">
              <div className="one-jobhunt-card-head">
                <div>
                  <strong>{item.role || 'Unknown role'}</strong>
                  <span>{item.company || 'Unknown company'} | {item.location || 'Location unknown'} | fit {item.fit_score || '0'}/100</span>
                </div>
                <span>{item.status.replace(/_/g, ' ')}</span>
              </div>
              <div className="one-jobhunt-stages">
                <small>Resume: {item.resume_version ? 'notes ready' : 'pending'}</small>
                <small>Email: {item.email_status.replace(/_/g, ' ')}</small>
                <small>Apply: {item.applied_status.replace(/_/g, ' ')}</small>
              </div>
              <p>{item.next_action}</p>
              <div className="one-jobhunt-actions">
                {item.job_url && <a href={item.job_url} target="_blank" rel="noreferrer">Open job <ExternalLink size={12} /></a>}
                {item.brief_path && <span title={item.brief_path}>Brief saved</span>}
                {item.resume_notes_path && <span title={item.resume_notes_path}>Resume notes saved</span>}
              </div>
            </article>
          ))}
        </div>
      </section>

      <section className="one-operations one-alfa-pipeline">
        <div className="one-operations-head">
          <div><div className="one-panel-label">ALFA REVENUE PIPELINE</div><strong>LEAD TO CASH OPERATING BOARD</strong></div>
          <span className="one-alfa-mrr">{alfaOpportunities.length} pending | estimates only, nothing is sent without approval</span>
        </div>
        <div className="one-revenue-summary">
          <div><span>Potential pipeline</span><strong>${alfaSummary.potential_pipeline.toLocaleString()}</strong></div>
          <div><span>Potential MRR</span><strong>${alfaSummary.potential_mrr.toLocaleString()}</strong></div>
          <div className="earned"><span>Collected revenue</span><strong>${alfaSummary.earned_revenue.toLocaleString()}</strong></div>
          <div className="earned"><span>Active MRR</span><strong>${alfaSummary.active_mrr.toLocaleString()}</strong></div>
        </div>
        {alfaMessage && <p className="one-alfa-message">{alfaMessage}</p>}
        <div className="one-alfa-list">
          {!alfaOpportunities.length && <p>No packaged leads waiting right now. Run ALFA to scan for new ones.</p>}
          {alfaOpportunities.map((opportunity) => {
            const expanded = alfaExpanded === opportunity.url;
            const busyOnThis = alfaActionUrl === opportunity.url;
            const stage = opportunity.pipeline_stage || (opportunity.approval_status === 'approved' ? 'outreach_approved' : 'qualified');
            return (
              <article key={opportunity.url} className={`one-alfa-card ${expanded ? 'expanded' : ''}`}>
                <button className="one-alfa-card-head" onClick={() => setAlfaExpanded(expanded ? null : opportunity.url)}>
                  <div>
                    <strong>{opportunity.title}</strong>
                    <span>{opportunity.service} | fit {opportunity.score}/100 | {opportunity.currency} {opportunity.budget_min.toLocaleString()}-{opportunity.budget_max.toLocaleString()}</span>
                  </div>
                  <span className="one-alfa-price">
                    ${opportunity.one_time_price.toLocaleString()}{opportunity.retainer_price ? ` + $${opportunity.retainer_price.toLocaleString()}/mo` : ''}
                  </span>
                </button>
                {expanded && (
                  <div className="one-alfa-card-body">
                    {opportunity.service_definition && <p className="one-alfa-offer">{opportunity.service_definition}</p>}
                    {!!opportunity.build_steps?.length && (
                      <ol className="one-alfa-steps">
                        {opportunity.build_steps.map((step, index) => <li key={index}>{step}</li>)}
                      </ol>
                    )}
                    {opportunity.retainer_pitch && <p className="one-alfa-retainer">{opportunity.retainer_pitch}</p>}
                    <p className="one-stage-badge">Stage: {stage.replace(/_/g, ' ')}</p>
                    {(stage === 'outreach_approved' || stage === 'contacted') && (
                      <div className="one-revenue-form">
                        <input placeholder="Client name (optional)" value={alfaForm.clientName} onChange={(event) => setAlfaForm({ ...alfaForm, clientName: event.target.value })} />
                        <input placeholder="Contact or username" value={alfaForm.clientContact} onChange={(event) => setAlfaForm({ ...alfaForm, clientContact: event.target.value })} />
                        <input placeholder="Channel, e.g. Reddit DM" value={alfaForm.channel} onChange={(event) => setAlfaForm({ ...alfaForm, channel: event.target.value })} />
                      </div>
                    )}
                    {stage === 'contacted' && (
                      <div className="one-revenue-form">
                        <textarea placeholder="Paste the client's response. Positive replies automatically create the deal documents." value={alfaForm.response} onChange={(event) => setAlfaForm({ ...alfaForm, response: event.target.value })} />
                      </div>
                    )}
                    {['replied', 'proposal_ready', 'payment_pending'].includes(stage) && (
                      <div className="one-revenue-form">
                        <input type="number" min="1" placeholder={`Amount received (suggested ${opportunity.one_time_price})`} value={alfaForm.amount} onChange={(event) => setAlfaForm({ ...alfaForm, amount: event.target.value })} />
                        <input placeholder="Payment transaction/reference ID" value={alfaForm.reference} onChange={(event) => setAlfaForm({ ...alfaForm, reference: event.target.value })} />
                        {(opportunity.proposal_path || opportunity.agreement_path || opportunity.invoice_path) && (
                          <div className="one-deal-links">
                            {opportunity.proposal_path && <a href={`/v1/alfa/artifact?kind=proposal&url=${encodeURIComponent(opportunity.url)}`} target="_blank" rel="noreferrer">Proposal</a>}
                            {opportunity.agreement_path && <a href={`/v1/alfa/artifact?kind=agreement&url=${encodeURIComponent(opportunity.url)}`} target="_blank" rel="noreferrer">Agreement draft</a>}
                            {opportunity.invoice_path && <a href={`/v1/alfa/artifact?kind=invoice&url=${encodeURIComponent(opportunity.url)}`} target="_blank" rel="noreferrer">Invoice draft</a>}
                          </div>
                        )}
                      </div>
                    )}
                    {opportunity.outreach_message && (
                      <div className="one-alfa-outreach">
                        <div className="one-alfa-outreach-head">
                          <span>Draft outreach (review before sending)</span>
                          <button onClick={() => void copyOutreach(opportunity.url, opportunity.outreach_message)}>
                            {alfaCopiedUrl === opportunity.url ? <><Check size={13} /> Copied</> : <><Copy size={13} /> Copy</>}
                          </button>
                        </div>
                        <p>{opportunity.outreach_message}</p>
                      </div>
                    )}
                    <div className="one-alfa-actions">
                      <a href={opportunity.url} target="_blank" rel="noreferrer" className="one-alfa-source">
                        View source post <ExternalLink size={13} />
                      </a>
                      {stage === 'qualified' && <button className="one-alfa-approve" disabled={busyOnThis} onClick={() => void approveOpportunity(opportunity.url)}><Check size={14} /> Approve outreach</button>}
                      {stage === 'outreach_approved' && <button className="one-alfa-approve" disabled={busyOnThis} onClick={() => void alfaAction('outreach-sent', { url: opportunity.url, channel: alfaForm.channel, client_contact: alfaForm.clientContact, client_name: alfaForm.clientName }, 'Contact recorded. Waiting for the client response.')}>Mark outreach sent</button>}
                      {stage === 'contacted' && <button className="one-alfa-approve" disabled={busyOnThis || !alfaForm.response.trim()} onClick={() => void alfaAction('response', { url: opportunity.url, response_text: alfaForm.response }, 'Response recorded. Positive replies create proposal, agreement, and invoice drafts.')}>Save client response</button>}
                      {['replied', 'proposal_ready', 'payment_pending'].includes(stage) && <button className="one-alfa-approve" disabled={busyOnThis || !alfaForm.amount || !alfaForm.reference.trim()} onClick={() => void alfaAction('payment', { url: opportunity.url, amount: Number(alfaForm.amount), reference: alfaForm.reference }, 'Payment recorded as collected. BETA delivery has been queued.')}>Confirm payment & start BETA</button>}
                      {['delivery_queued', 'delivering'].includes(stage) && <button className="one-alfa-approve" disabled={busyOnThis} onClick={() => void alfaAction('complete', { url: opportunity.url, activate_retainer: false }, 'Delivery marked complete. Retainer remains proposed.')}>Mark delivered</button>}
                      {!['paid', 'delivery_queued', 'delivering', 'delivered', 'retainer'].includes(stage) && (
                        <button className="one-alfa-dismiss" disabled={busyOnThis} onClick={() => void dismissOpportunity(opportunity.url)}>
                          <XCircle size={14} /> Dismiss
                        </button>
                      )}
                    </div>
                  </div>
                )}
              </article>
            );
          })}
        </div>
      </section>
      </aside>
      {memoryOpen && (
        <div className="one-modal-backdrop" onMouseDown={() => setMemoryOpen(false)}>
          <section className="one-memory-modal" onMouseDown={(event) => event.stopPropagation()}>
            <button className="one-modal-close" title="Close" onClick={() => setMemoryOpen(false)}><X size={20} /></button>
            <Database size={28} />
            <div className="one-panel-label">LOCAL MEMORY</div>
            <h2>Connect Obsidian</h2>
            <p>ONE searches your Markdown notes locally. Nothing is uploaded.</p>
            <label>Vault folder path</label>
            <input value={vaultPath} onChange={(event) => setVaultPath(event.target.value)} placeholder="C:\Users\pc\Documents\ONE Vault" />
            <button className="one-primary" onClick={() => void connectObsidian()}>Connect vault</button>
            {memoryMessage && <small>{memoryMessage}</small>}
            {status.obsidian.connected && <small>{status.obsidian.notes} notes active</small>}
            <a href="obsidian://open" target="_blank" rel="noreferrer">Open Obsidian <ExternalLink size={14} /></a>
          </section>
        </div>
      )}
    </main>
  );
}
