/** Markdown task spec loaded from the Specs file tree into the Bots tab. */

export type BotSpecFile = {
  path: string;
  name: string;
  content: string;
  loadedAt: number;
};

export const AGENT_BOT_ID = 'agent_reference_fishing';
