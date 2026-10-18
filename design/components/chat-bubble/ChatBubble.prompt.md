One chat message between the shop owner and the copilot; copilot messages can carry FactNumbers and an attached ApprovalCard.

```jsx
<ChatBubble role="owner" meta="9:12 am">Can I afford to restock flour this week?</ChatBubble>
<ChatBubble role="copilot" avatarSrc="assets/logo-mark.png" meta="9:12 am">
  Yes. After payroll you'll have <FactNumber onClick={trace}>$4,280</FactNumber> left. The restock is $1,240.
</ChatBubble>
```

- Owner: right, `surface-raised` bubble, sans 15/22, fully rounded.
- Copilot: left, no bubble. Newsreader 19/30 (`--font-advisor`) directly on the surface, mark avatar. The serif is what makes it a conversation — never use it elsewhere.
- 24px between messages; no dividers.
- Copilot copy: short sentences, numbers first, no exclamation marks or emoji.
