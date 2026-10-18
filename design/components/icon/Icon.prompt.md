Renders any Lucide icon at the KaChing 1.5px stroke; use it for every icon in the product.

```jsx
<Icon name="shield-alert" size={20} />
<span className="kc-label"><Icon name="clock" size={16} /> Waiting</span>
```

- `name` is the Lucide kebab-case name (lucide.dev). Pinned to lucide@0.460.0, loaded from CDN on first render.
- Sizes: 16 next to labels and pills, 20 default, 24 for empty states. Never change `strokeWidth`.
- Color follows `currentColor`; set color on the parent.
