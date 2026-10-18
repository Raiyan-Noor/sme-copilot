One signed permission tier — mode, money limit and the tools the copilot may use; stack them in a Card to show the owner's full set of limits.

```jsx
<TierRow tier={1} name="Everyday upkeep" mode="auto" limit="$200 per action"
  tools={['Send payment reminders', 'Categorize transactions']} signedNote="Signed by Maria Lopez, Sep 2" onEdit={edit} />
<TierRow tier={2} name="Paying suppliers" mode="approval" limit="$2,000 per action" tools={['Pay bills', 'Schedule transfers']} />
<TierRow tier={3} name="Taking on debt" mode="never" tools={['Accept loan offers']} />
```

- Modes: `auto` (Acts on its own, green), `approval` (Asks first, burnt orange), `never` (red). Each shows icon + words.
- Rows have hairline separators; place several inside one `Card` with `padding="sm"`.
