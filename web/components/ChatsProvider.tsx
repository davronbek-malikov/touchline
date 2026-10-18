"use client";

import { createContext, useCallback, useContext, useEffect, useState } from "react";

import { api, ChatSummary, Folder } from "@/lib/api";

interface ChatsState {
  folders: Folder[];
  chats: ChatSummary[];
  loaded: boolean;
  error: string | null;
  refresh: () => Promise<void>;
}

const Ctx = createContext<ChatsState | null>(null);

/** The sidebar's chat list and folders, shared with the chat view so new chats appear at once. */
export function ChatsProvider({ children }: { children: React.ReactNode }) {
  const [folders, setFolders] = useState<Folder[]>([]);
  const [chats, setChats] = useState<ChatSummary[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const r = await api.chats();
      setFolders(r.folders);
      setChats(r.chats);
      setError(null);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoaded(true);
    }
  }, []);

  useEffect(() => { refresh(); }, [refresh]);

  return <Ctx.Provider value={{ folders, chats, loaded, error, refresh }}>{children}</Ctx.Provider>;
}

export function useChats(): ChatsState {
  const v = useContext(Ctx);
  if (!v) throw new Error("useChats outside ChatsProvider");
  return v;
}
