The KaChing action button (shadcn Button); use one primary per view, labels verb first in sentence case.

```jsx
<Button variant="primary" iconLeft="pen-line">Sign and approve</Button>
<Button variant="secondary">Prepare reminder</Button>
<Button variant="ghost" iconRight="arrow-right">See the trace</Button>
<Button variant="destructive" iconLeft="ban">Block payment</Button>
```

- Variants: `primary` (logo green #01775A fill, white text), `secondary` (surface-raised fill, no border), `ghost` (brand-primary text), `destructive` (coral text + thin coral outline, fraud and blocked actions only).
- Fully rounded. No shadows.
- Sizes: `sm` 32px, `md` 40px (default), `lg` 48px.
- `loading` swaps the left icon for a spinner and disables the button.
- Copy: "Sign and approve", "Prepare reminder", "Pay now". Never "Submit", "OK", or exclamation marks.
