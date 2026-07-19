import { useCallback, useEffect, useState } from 'react';
import { Check, ExternalLink, RefreshCw, Settings2, Wallet, X, XCircle } from 'lucide-react';
import { getBase } from '../lib/api';
import './one-cockpit.css';

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
  { id: 'deepgram', label: 'Deepgram', section: 'speech_deepgram', keys: ['DEEPGRAM_API_KEY'], note: 'Cloud speech-to-text, preferred over local Whisper when set' },
  { id: 'tavily', label: 'Tavily', section: 'web_search', keys: ['TAVILY_API_KEY'], note: 'Real search API for the Ghost Agent -- replaces the DuckDuckGo scraper, which gets rate-limited' },
];

const coreUrl = (path: string) => `${getBase()}${path}`;
const coreFetch = (path: string, init?: RequestInit) => fetch(coreUrl(path), init);

export function CredentialVaultPage() {
  const [credentialVault, setCredentialVault] = useState<CredentialVault>(DEFAULT_CREDENTIAL_VAULT);
  const [credentialVaultMessage, setCredentialVaultMessage] = useState('');
  const [credentialActionKey, setCredentialActionKey] = useState<string | null>(null);
  const [selectedConnectionId, setSelectedConnectionId] = useState(CONNECTION_PRESETS[0].id);
  const selectedConnection = CONNECTION_PRESETS.find((preset) => preset.id === selectedConnectionId) || CONNECTION_PRESETS[0];
  const [credentialForm, setCredentialForm] = useState({ section: selectedConnection.section, key: selectedConnection.keys[0], value: '' });

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

  return (
    <main className="one-shell one-vault-page">
      <div className="one-grid" />
      <section className="one-operations one-credential-vault one-vault-page-panel">
        <div className="one-operations-head">
          <div><div className="one-panel-label">CREDENTIAL VAULT</div><strong>MASKED LOCAL SECRETS</strong></div>
          <span className="one-alfa-mrr">{credentialVault.count} saved | values hidden</span>
        </div>
        <div className="one-vault-toolbar">
          <span title={credentialVault.path}>{credentialVault.exists ? 'Vault file active' : 'Vault file not found'}</span>
          <div className="one-vault-top-actions">
            <a href="/" title="Back to ONE cockpit"><ExternalLink size={13} /> ONE</a>
            <button onClick={() => void refreshCredentialVault()}><RefreshCw size={13} /> Refresh</button>
          </div>
        </div>
        {credentialVaultMessage && <p className="one-alfa-message">{credentialVaultMessage}</p>}
        <div className="one-vault-shell">
          <div className="one-vault-list">
            {!credentialVault.entries.length && <p>No credentials saved in ONE vault yet.</p>}
            {credentialVault.entries.map((entry) => (
              <article key={`${entry.section}-${entry.key}`} className={entry.active ? 'active' : ''}>
                <div>
                  <Wallet size={14} />
                  <div>
                    <strong>{entry.key}</strong>
                    <span>{entry.section} | {entry.active ? 'loaded in process' : 'saved, restart may be needed'}</span>
                  </div>
                </div>
                <code>{entry.masked}</code>
                <div className="one-vault-actions">
                  <button title={`Update ${entry.key}`} disabled={credentialActionKey === entry.key} onClick={() => editVaultCredential(entry)}>
                    <Settings2 size={13} /> Update
                  </button>
                  <button className="danger" title={`Remove ${entry.key} from the vault`} disabled={credentialActionKey === entry.key} onClick={() => void deleteVaultCredential(entry)}>
                    <XCircle size={13} /> Remove
                  </button>
                </div>
              </article>
            ))}
          </div>
          <aside className="one-connection-rail">
            <div className="one-panel-label">CONNECTIONS</div>
            <strong>{selectedConnection.label}</strong>
            <small>{selectedConnection.note}</small>
            <div className="one-connection-buttons">
              {CONNECTION_PRESETS.map((preset) => {
                const configured = preset.keys.some((key) => credentialVault.entries.some((entry) => entry.key === key));
                return (
                  <button key={preset.id} className={preset.id === selectedConnection.id ? 'selected' : ''} onClick={() => pickConnection(preset)}>
                    <span>{preset.label}</span>
                    <i className={configured ? 'online' : ''} />
                  </button>
                );
              })}
            </div>
            <div className="one-vault-editor">
              <select
                aria-label="Credential key"
                value={credentialForm.key}
                onChange={(event) => setCredentialForm((current) => ({ ...current, section: selectedConnection.section, key: event.target.value, value: '' }))}
              >
                {selectedConnection.keys.map((key) => <option key={key} value={key}>{key}</option>)}
              </select>
              <input
                aria-label="Credential value"
                placeholder="Paste new secret value"
                type="password"
                value={credentialForm.value}
                onChange={(event) => setCredentialForm((current) => ({ ...current, section: selectedConnection.section, value: event.target.value }))}
              />
              <button disabled={Boolean(credentialActionKey) || !credentialForm.key.trim() || !credentialForm.value.trim()} onClick={() => void saveVaultCredential()}>
                <Check size={13} /> Save / Update
              </button>
              <button className="ghost" disabled={!credentialForm.value} onClick={() => setCredentialForm((current) => ({ ...current, value: '' }))}>
                <X size={13} /> Clear
              </button>
            </div>
          </aside>
        </div>
      </section>
    </main>
  );
}
