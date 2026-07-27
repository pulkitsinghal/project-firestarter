# Chat composer key and state map

The native assistant composer uses a true multiline text area. This keeps
message submission distinct from editing:

```text
editable draft
├─ Shift-Return ─> insert newline ─> editable draft
└─ Return ───────> can send?
                   ├─ yes ─> submit bounded draft ─> clear composer
                   └─ no  ─> keep draft unchanged
```

| Input | Result |
|---|---|
| Return with a non-empty ready draft | Sends the draft and clears the composer |
| Shift-Return | Inserts a newline and makes no Router request |
| Return while disabled, empty, or already sending | Makes no request and retains any draft |
| Send button or Command-Return | Uses the same bounded send path |

## Rebuilt-app evidence

The frame below uses only synthetic text. It shows the multiline draft after
typing `First line`, pressing Shift-Return, and typing `Second line`; no message
had been sent when the frame was captured.

![Multiline native assistant composer](media/chat-composer-multiline.jpg)

The live acceptance path then pressed Return and observed one two-line user
message plus an empty composer. The retry path disables or clears chat, both of
which cancel in-flight work and remove the in-memory conversation.
