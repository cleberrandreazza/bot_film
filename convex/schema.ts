import { defineSchema, defineTable } from "convex/server";
import { v } from "convex/values";

// Espelha as tabelas SQLite originais (db_utils.py). evento_participantes
// passa a referenciar discord_event_id (chave estavel) em vez do id inteiro.
export default defineSchema({
  listas: defineTable({
    user_id: v.string(),
    filme_id: v.string(),
    titulo: v.string(),
    status: v.string(), // "watchlist" | "assistido"
  })
    .index("by_filme", ["filme_id"])
    .index("by_status", ["status"]),

  eventos: defineTable({
    discord_event_id: v.string(),
    filme_id: v.string(),
    titulo: v.string(),
    data_evento: v.string(),
    canal_id: v.optional(v.string()),
    guild_id: v.optional(v.string()),
    status: v.string(), // agendado | ativo | encerrado | cancelado
    canal_temporario: v.number(),
  })
    .index("by_discord_event", ["discord_event_id"])
    .index("by_status", ["status"])
    .index("by_canal", ["canal_id"]),

  evento_participantes: defineTable({
    discord_event_id: v.string(),
    user_id: v.string(),
    username: v.optional(v.string()),
    interessado: v.number(),
    entrou_canal: v.number(),
  })
    .index("by_evento", ["discord_event_id"])
    .index("by_evento_and_user", ["discord_event_id", "user_id"]),

  usuarios_assistidos: defineTable({
    filme_id: v.string(),
    user_id: v.string(),
    username: v.optional(v.string()),
    display_name: v.optional(v.string()),
    avatar: v.optional(v.string()),
    source: v.string(), // manual | evento
    data_assistido: v.string(),
  })
    .index("by_filme", ["filme_id"])
    .index("by_filme_and_user", ["filme_id", "user_id"]),
});
