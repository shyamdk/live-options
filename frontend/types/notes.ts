export interface Note {
  id: number;
  day: string;
  title: string;
  body: string;
  tags: string[];
  createdAt: number;
  updatedAt: number;
}

export interface NotesDigest {
  overview: string;
  keyLearnings: string[];
  rules: string[];
  recurringMistakes: string[];
  openQuestions: string[];
  noteCount: number;
  notesUsed: number;
  model: string;
  generatedAt: number;
  stale: boolean;
}

export interface NotesSummary {
  stats: {
    notes: number;
    days: number;
    first: string | null;
    last: string | null;
    byMonth: { month: string; count: number }[];
    topTags: { tag: string; count: number }[];
  };
  digest: NotesDigest | null;
  aiAvailable: boolean;
  aiPausedMessage?: string | null;
}

export interface NoteInput {
  day: string;
  title: string;
  body: string;
  tags: string[];
}
