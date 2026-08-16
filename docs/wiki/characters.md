# Characters

Characters live in the Control Plane and can be assigned to active sessions.

## Create A Character

1. Open `/control`.
2. Select a campaign.
3. Open the **Characters** tab.
4. Use the builder form for manual creation, or enter a concept and use
   **AI Generate** to create and save a character through the configured local
   or hosted LLM provider.

AI generation is a create-and-save action in the current UI. If generation
fails, the concept text stays in place so the GM can revise it.

## Control And Ownership

- Player characters can be assigned to a player principal.
- AI-controlled NPCs and party members use the campaign AI controller principal.
- The Game Console renders command controls only for entities controlled by the
  active principal, or for the GM inspection view.

## Session Party

Characters are not automatically active in every session. Add them to the
current session from the **Current Session Party** panel. Dead characters must
be revived before they can rejoin a session.

## Join Links

Use the **Players / Join** panel to create local player principals and join
codes. A player should open `/game` through the generated link so the browser
stores the correct principal and join token.
