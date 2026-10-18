"use client";

import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { FormEvent, useEffect, useRef, useState } from "react";

import { useChats } from "@/components/ChatsProvider";
import { api, ChatSummary, Folder } from "@/lib/api";

const NAV = [
  { href: "/", label: "Scout Assistant" },
  { href: "/shortlist", label: "Shortlists" },
  { href: "/compare", label: "Compare" },
  { href: "/notes", label: "Notes" },
  { href: "/about", label: "About the data" },
];

/** A small ⋯ menu that closes on outside click or Escape. */
function Menu({ label, children }: { label: string; children: (close: () => void) => React.ReactNode }) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => { if (!ref.current?.contains(e.target as Node)) setOpen(false); };
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => { document.removeEventListener("mousedown", onDown); document.removeEventListener("keydown", onKey); };
  }, [open]);
  return (
    <div className="menu" ref={ref}>
      <button className="menu-btn" aria-label={label} aria-expanded={open} onClick={() => setOpen((o) => !o)}>⋯</button>
      {open && <div className="menu-pop" role="menu">{children(() => setOpen(false))}</div>}
    </div>
  );
}

function InlineName({ initial, onSave, onCancel }: { initial: string; onSave: (v: string) => void; onCancel: () => void }) {
  const [v, setV] = useState(initial);
  return (
    <form className="inline-name" onSubmit={(e: FormEvent) => { e.preventDefault(); if (v.trim()) onSave(v.trim()); }}>
      <input autoFocus value={v} onChange={(e) => setV(e.target.value)} onBlur={onCancel} maxLength={80}
             onKeyDown={(e) => e.key === "Escape" && onCancel()} aria-label="Name" />
    </form>
  );
}

function ChatRow({ chat, folders, active, onError }: {
  chat: ChatSummary; folders: Folder[]; active: boolean; onError: (m: string) => void;
}) {
  const { refresh } = useChats();
  const router = useRouter();
  const [renaming, setRenaming] = useState(false);
  const run = (p: Promise<unknown>) => p.then(refresh).catch((e) => onError(e.message));

  if (renaming) {
    return (
      <li className="chat-row">
        <InlineName initial={chat.title} onCancel={() => setRenaming(false)}
                    onSave={(t) => { setRenaming(false); run(api.renameChat(chat.chat_id, t)); }} />
      </li>
    );
  }
  return (
    <li className={`chat-row${active ? " is-active" : ""}`}>
      <Link href={`/?chat=${chat.chat_id}`} aria-current={active ? "page" : undefined} title={chat.title}>{chat.title}</Link>
      <Menu label={`Options for ${chat.title}`}>
        {(close) => (
          <>
            <button role="menuitem" onClick={() => { close(); setRenaming(true); }}>Rename</button>
            {folders.length > 0 && <span className="menu-label">Move to</span>}
            {folders.filter((f) => f.folder_id !== chat.folder_id).map((f) => (
              <button key={f.folder_id} role="menuitem" onClick={() => { close(); run(api.moveChat(chat.chat_id, f.folder_id)); }}>
                {f.name}
              </button>
            ))}
            {chat.folder_id && (
              <button role="menuitem" onClick={() => { close(); run(api.moveChat(chat.chat_id, null)); }}>Out of folder</button>
            )}
            <button role="menuitem" className="danger" onClick={() => {
              close();
              if (window.confirm(`Delete “${chat.title}”? This can't be undone.`)) {
                run(api.deleteChat(chat.chat_id).then(() => { if (active) router.push("/"); }));
              }
            }}>Delete</button>
          </>
        )}
      </Menu>
    </li>
  );
}

function FolderBlock({ folder, chats, folders, activeChat, onError }: {
  folder: Folder; chats: ChatSummary[]; folders: Folder[]; activeChat: string | null; onError: (m: string) => void;
}) {
  const { refresh } = useChats();
  const [open, setOpen] = useState(true);
  const [renaming, setRenaming] = useState(false);
  const run = (p: Promise<unknown>) => p.then(refresh).catch((e) => onError(e.message));
  return (
    <li className="folder">
      <div className="folder-head">
        {renaming ? (
          <InlineName initial={folder.name} onCancel={() => setRenaming(false)}
                      onSave={(n) => { setRenaming(false); run(api.renameFolder(folder.folder_id, n)); }} />
        ) : (
          <button className="folder-toggle" aria-expanded={open} onClick={() => setOpen((o) => !o)}>
            <span aria-hidden>{open ? "▾" : "▸"}</span> {folder.name}
            <span className="folder-count">{chats.length}</span>
          </button>
        )}
        <Menu label={`Options for folder ${folder.name}`}>
          {(close) => (
            <>
              <button role="menuitem" onClick={() => { close(); setRenaming(true); }}>Rename</button>
              <button role="menuitem" className="danger" onClick={() => {
                close();
                if (window.confirm(`Delete the folder “${folder.name}”? Its chats are kept and move back to the main list.`)) {
                  run(api.deleteFolder(folder.folder_id));
                }
              }}>Delete folder</button>
            </>
          )}
        </Menu>
      </div>
      {open && (
        <ul className="chat-list">
          {chats.map((c) => <ChatRow key={c.chat_id} chat={c} folders={folders} active={c.chat_id === activeChat} onError={onError} />)}
          {chats.length === 0 && <li className="rail-empty">Move chats here from their ⋯ menu.</li>}
        </ul>
      )}
    </li>
  );
}

export default function Rail() {
  const path = usePathname();
  const params = useSearchParams();
  const router = useRouter();
  const { folders, chats, error, refresh } = useChats();
  const [drawer, setDrawer] = useState(false);
  const [newFolder, setNewFolder] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const activeChat = path === "/" ? params.get("chat") : null;
  const active = (href: string) => (href === "/" ? path === "/" : path.startsWith(href));

  useEffect(() => { setDrawer(false); }, [path, params]);

  const unfiled = chats.filter((c) => !c.folder_id || !folders.some((f) => f.folder_id === c.folder_id));

  return (
    <aside className={`rail${drawer ? " is-open" : ""}`}>
      <div className="rail-top">
        <Link href="/" className="wordmark">Touchline</Link>
        <button className="rail-toggle" aria-expanded={drawer} aria-controls="rail-body" onClick={() => setDrawer((d) => !d)}>
          {drawer ? "Close" : "Menu"}
        </button>
      </div>
      <div className="rail-body" id="rail-body">
        <button className="new-chat" onClick={() => router.push(`/?new=${Date.now()}`)}>New chat</button>
        <nav className="nav" aria-label="Main">
          {NAV.map((n) => (
            <Link key={n.href} href={n.href} aria-current={active(n.href) ? "page" : undefined}>{n.label}</Link>
          ))}
        </nav>

        <section className="rail-section" aria-label="Folders and chats">
          <div className="rail-section-head">
            <h2>Folders</h2>
            <button className="menu-btn" aria-label="New folder" onClick={() => setNewFolder(true)}>+</button>
          </div>
          <ul className="folder-list">
            {newFolder && (
              <li>
                <InlineName initial="" onCancel={() => setNewFolder(false)}
                            onSave={(n) => { setNewFolder(false); api.addFolder(n).then(refresh).catch((e) => setErr(e.message)); }} />
              </li>
            )}
            {folders.map((f) => (
              <FolderBlock key={f.folder_id} folder={f} folders={folders} activeChat={activeChat} onError={setErr}
                           chats={chats.filter((c) => c.folder_id === f.folder_id)} />
            ))}
            {folders.length === 0 && !newFolder && <li className="rail-empty">Group chats by window, position or club.</li>}
          </ul>

          <div className="rail-section-head"><h2>Chats</h2></div>
          <ul className="chat-list">
            {unfiled.map((c) => <ChatRow key={c.chat_id} chat={c} folders={folders} active={c.chat_id === activeChat} onError={setErr} />)}
            {unfiled.length === 0 && <li className="rail-empty">{error ? "Chats are unavailable right now." : "Your chats will appear here."}</li>}
          </ul>
          {err && <p className="rail-error" role="alert">{err}</p>}
        </section>

        <p className="rail-foot">Market data as of 6 July 2026. Event data from StatsBomb open data.</p>
      </div>
    </aside>
  );
}
