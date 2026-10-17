"use client";

import Link from "next/link";
import { useState } from "react";

import NotesPanel from "@/components/NotesPanel";
import PlayerPicker from "@/components/PlayerPicker";
import { euros, PlayerRow } from "@/lib/api";

export default function NotesPage() {
  const [player, setPlayer] = useState<PlayerRow | null>(null);
  return (
    <div className="page" style={{ maxWidth: 820 }}>
      <h1>Scout notes</h1>
      <p className="lede">
        Write down what you saw. Notes are searchable by the agent as soon as you save them, and reports cite them like any other source.
      </p>
      <div style={{ marginTop: 24 }}>
        <PlayerPicker label="Which player?" onPick={setPlayer} />
      </div>
      {player && (
        <section className="panel" style={{ marginTop: 24 }}>
          <h2><Link href={`/players/${player.player_id}`} style={{ textDecoration: "none" }}>{player.name}</Link></h2>
          <p className="hint">{[player.age, player.club_name, euros(player.market_value_eur)].filter((x) => x != null && x !== "–").join(", ")}</p>
          <NotesPanel playerId={player.player_id} playerName={player.name} />
        </section>
      )}
    </div>
  );
}
