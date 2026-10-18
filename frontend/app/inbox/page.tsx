"use client";

import { NotYetAvailable, PageHeader, Section } from "@/components/data";

export default function InboxPage() {
  return (
    <>
      <PageHeader title="Inbox" />
      <Section title="Finance emails">
        <NotYetAvailable what="The quarantined mailbox and Inbox Sentinel findings" prompt="12" />
      </Section>
    </>
  );
}
