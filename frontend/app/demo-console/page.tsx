import { notFound } from "next/navigation";

/**
 * The demo console route. The screen lives in the root layout (components/advisor/shell.tsx); without
 * NEXT_PUBLIC_DEMO_MODE the route does not exist.
 */
export default function Page() {
  if (process.env.NEXT_PUBLIC_DEMO_MODE !== "true") notFound();
  return null;
}
