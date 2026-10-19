"use client";

import {
  ArrowLeft,
  ArrowRight,
  CircleAlert,
  CircleCheck,
  FileUp,
  Inbox,
  Mail,
  PenLine,
  Plus,
  ShieldAlert,
  Trash2,
  Upload,
} from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";

import { Logo } from "@/components/brand/Logo";
import { useBusiness } from "@/components/business-context";
import { Badge } from "@/components/kc/badge";
import { Button } from "@/components/kc/button";
import { Card } from "@/components/kc/card";
import { ChatBubble } from "@/components/kc/chat-bubble";
import { FactText } from "@/components/kc/fact";
import { StatusPill } from "@/components/kc/status-pill";
import { APP_NAME } from "@/config/app";
import { api } from "@/lib/api";
import { errorMessage } from "@/lib/errors";
import { flagLabel, money } from "@/lib/format";
import { ensureEnrolled, signMessage } from "@/lib/owner-key";
import type {
  Bill,
  BusinessInfo,
  ContactIn,
  DataNeed,
  FinishResult,
  InboxRecord,
  OnboardingView,
  SuggestedMandate,
  UploadResult,
} from "@/lib/types";
import { cn } from "@/lib/utils";

import { type SkillChoice, SkillPicker } from "./skill-picker";
import { StageLine } from "./stage-line";

type Step =
  | "skill"
  | "name"
  | "currency"
  | "cash"
  | "bills"
  | "questions"
  | "needs"
  | "contacts"
  | "inbox"
  | "summary"
  | "rules"
  | "finishing"
  | "done";

const ORDER: Step[] = [
  "skill",
  "name",
  "currency",
  "cash",
  "bills",
  "questions",
  "needs",
  "contacts",
  "inbox",
  "summary",
  "rules",
  "finishing",
  "done",
];
const CURRENCIES = ["USD", "EUR", "GBP", "INR", "BDT"];
const MANDATE_DAYS = 30;
const KIND_LABEL: Record<UploadResult["kind"], string> = {
  bank: "Bank statement",
  sales: "Sales per product",
  products: "Products",
  ad_spend: "Ad spend",
  invoice: "Invoice",
  receipt: "Receipt",
  unknown: "Unrecognised",
};

/** Minor units from what the owner typed ("1,250.50"), or null if it is not an amount. */
function toMinor(text: string): number | null {
  const clean = text.replace(/[^0-9.]/g, "");
  if (!clean || !/^\d+(\.\d{0,2})?$/.test(clean)) return null;
  return Math.round(parseFloat(clean) * 100);
}

/** Upload order: products before the sales that are matched to them, CSVs before documents. */
function uploadRank(f: File): number {
  const n = f.name.toLowerCase();
  if (n.endsWith(".csv")) return n.includes("product") ? 0 : 1;
  return 2;
}

/**
 * Onboarding from zero (feature plans P1 and P8): a new business set up in a short chat, one question at a time,
 * driven by the skill the owner picks first (built-in, or their own uploaded skill.md, previewed before use). Files go through the same ingestion, quarantine and sentinel as everywhere else; starter limits
 * are signed in this browser (invariant 6); every figure is a Fact (invariant 4).
 */
export function Onboarding() {
  const router = useRouter();
  const { select, resetSession } = useBusiness();
  const [step, setStep] = useState<Step>("skill");
  const [name, setName] = useState("");
  const [skill, setSkill] = useState<SkillChoice | null>(null);
  const [biz, setBiz] = useState<BusinessInfo | null>(null);
  const [view, setView] = useState<OnboardingView | null>(null);
  const [said, setSaid] = useState<Partial<Record<Step | string, string>>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [finished, setFinished] = useState<FinishResult | null>(null);
  const end = useRef<HTMLDivElement>(null);

  const at = (s: Step) => ORDER.indexOf(step) >= ORDER.indexOf(s);
  const id = biz?.id ?? "";
  const currency = biz?.currency ?? "USD";

  useEffect(() => {
    const t = setTimeout(() => end.current?.scrollIntoView({ behavior: "smooth", block: "end" }), 60);
    return () => clearTimeout(t);
  }, [step, view, finished]);

  const run = async (fn: () => Promise<void>) => {
    setBusy(true);
    setError(null);
    try {
      await fn();
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  };
  const say = (key: string, text: string) => setSaid((s) => ({ ...s, [key]: text }));

  const create = (cur: string) =>
    run(async () => {
      const created = await api.startOnboarding({
        name,
        business_type: skill?.name || "shop",
        currency: cur,
        pack_id: skill?.pack_id ?? null,
        skill_sha256: skill?.skill_sha256 ?? null,
      });
      setBiz(created);
      setView(await api.onboarding(created.id));
      say("currency", cur);
      setStep("cash");
    });

  const finish = () =>
    run(async () => {
      setStep("finishing");
      try {
        setFinished(await api.finishOnboarding(id));
        setStep("done");
      } catch (e) {
        setStep("rules");
        throw e;
      }
    });

  const openApp = () => {
    select(id);
    resetSession();
    router.push("/");
  };

  return (
    <div className="ka-onb">
      <header className="ka-onb__head">
        <Logo />
        <Button variant="ghost" size="sm" iconLeft={ArrowLeft} onClick={() => router.push("/")}>
          Back to {APP_NAME}
        </Button>
      </header>
      <div className="ka-scroll">
        <div className="ka-col ka-msgs ka-onb__msgs" role="log" aria-label="Set up a new business">
          <ChatBubble role="copilot" name={APP_NAME}>
            Hi, I am {APP_NAME}. Let us set up your business; it takes about two minutes. First, pick a skill: it teaches
            me how your kind of business runs, what to look at and what to ask you.
          </ChatBubble>
          {step === "skill" ? (
            <SkillPicker
              onPick={(c) => {
                setSkill(c);
                say("skill", c.skill_sha256 ? `Use my own skill: ${c.name}` : c.name);
                setStep("name");
              }}
            />
          ) : (
            <Owner text={said.skill} />
          )}

          {at("name") ? (
            <ChatBubble role="copilot" name={APP_NAME}>
              Good choice. What is your business called?
            </ChatBubble>
          ) : null}
          {step === "name" ? (
            <TextAsk
              placeholder="Business name"
              onSubmit={(v) => {
                setName(v);
                say("name", v);
                setStep("currency");
              }}
            />
          ) : at("currency") ? (
            <Owner text={said.name} />
          ) : null}

          {at("currency") ? (
            <ChatBubble role="copilot" name={APP_NAME}>
              Which currency do you work in?
            </ChatBubble>
          ) : null}
          {step === "currency" ? (
            <Chips options={CURRENCIES} disabled={busy} onPick={create} />
          ) : at("cash") ? (
            <Owner text={said.currency} />
          ) : null}

          {at("cash") && view ? (
            <ChatBubble role="copilot" name={APP_NAME}>
              Done: {name} is set up with the {view.plan.pack_name} Skill Pack. How much cash do you have on hand today,
              outside the bank? Skip it if you are not sure.
            </ChatBubble>
          ) : null}
          {step === "cash" ? (
            <CashAsk
              currency={currency}
              busy={busy}
              onSubmit={(minor, text) =>
                run(async () => {
                  if (minor !== null)
                    setView(
                      await api.setStartingPoint(id, {
                        cash_on_hand_minor: minor,
                        bills: [],
                      }),
                    );
                  say("cash", text);
                  setStep("bills");
                })
              }
            />
          ) : at("bills") ? (
            <Owner text={said.cash} />
          ) : null}

          {at("bills") ? (
            <ChatBubble role="copilot" name={APP_NAME}>
              Do you pay any regular bills or loan instalments, like rent, power or internet? Add the ones you know.
            </ChatBubble>
          ) : null}
          {step === "bills" ? (
            <BillsAsk
              currency={currency}
              busy={busy}
              onSubmit={(bills) =>
                run(async () => {
                  if (bills.length) setView(await api.setStartingPoint(id, { bills }));
                  say("bills", bills.length ? bills.map((b) => b.name).join(", ") : "No regular bills for now");
                  setStep(view?.plan.questions.length ? "questions" : "needs");
                })
              }
            />
          ) : at("questions") ? (
            <Owner text={said.bills} />
          ) : null}

          {at("questions") && view ? (
            <Questions
              view={view}
              active={step === "questions"}
              busy={busy}
              said={said}
              onAnswer={(qid, option, label) =>
                run(async () => {
                  setView(await api.answer(id, { question_id: qid, option }));
                  say(`q:${qid}`, label);
                  const next = view.plan.questions.find(
                    (q) => q.id !== qid && !(q.id in view.answers) && !said[`q:${q.id}`],
                  );
                  if (!next) setStep("needs");
                })
              }
            />
          ) : null}

          {at("needs") && view ? (
            <Needs
              id={id}
              view={view}
              currency={currency}
              active={step === "needs"}
              onView={setView}
              onDone={() => setStep("contacts")}
            />
          ) : null}

          {at("contacts") && view ? (
            <ContactsStep
              view={view}
              active={step === "contacts"}
              busy={busy}
              onConfirm={(contacts) =>
                run(async () => {
                  setView(await api.confirmContacts(id, { contacts }));
                  say(
                    "contacts",
                    contacts.length ? `Confirmed ${contacts.map((c) => c.name).join(", ")}` : "None for now",
                  );
                  setStep("inbox");
                })
              }
              said={said.contacts}
            />
          ) : null}

          {at("inbox") ? (
            <ChatBubble role="copilot" name={APP_NAME}>
              Where do your invoices arrive? I read your inbox in quarantine: nothing in an email can make me act, and I
              hold anything that looks like a scam.
            </ChatBubble>
          ) : null}
          {step === "inbox" ? (
            <div className="ka-onb__row">
              <Button variant="secondary" iconLeft={Mail} disabled title="Gmail connection arrives in the next build">
                Connect Gmail (soon)
              </Button>
              <Button
                iconLeft={Inbox}
                loading={busy}
                onClick={() =>
                  run(async () => {
                    setView(await api.setInbox(id, { connection: "sandbox" }));
                    say("inbox", "Use the sandbox inbox");
                    setStep("summary");
                  })
                }
              >
                Use sandbox inbox
              </Button>
              <Button variant="ghost" onClick={() => (say("inbox", "Later"), setStep("summary"))}>
                Later
              </Button>
            </div>
          ) : at("summary") ? (
            <Owner text={said.inbox} />
          ) : null}

          {at("summary") && view ? (
            <ChatBubble
              role="copilot"
              name={APP_NAME}
              attachment={
                <Card padding="md" eyebrow="What I understood">
                  <ul className="ka-foldlist ka-insights">
                    {view.summary.map((s, i) => (
                      <li key={i}>
                        <span className="w">
                          <span className="kc-caption">{s.label}</span>
                          <span>
                            <FactText text={s.text} facts={view.facts} />
                          </span>
                        </span>
                      </li>
                    ))}
                  </ul>
                </Card>
              }
            >
              Before I start, here is what I understood. Is this right?
            </ChatBubble>
          ) : null}
          {step === "summary" ? (
            <div className="ka-onb__row">
              <Button
                iconLeft={CircleCheck}
                onClick={() => {
                  say("summary", "That is right");
                  setStep("rules");
                }}
              >
                That is right
              </Button>
              <Button variant="secondary" iconLeft={ArrowLeft} onClick={() => setStep("needs")}>
                Add more files
              </Button>
            </div>
          ) : at("rules") ? (
            <Owner text={said.summary} />
          ) : null}

          {at("rules") && view ? (
            <Rules id={id} view={view} active={step === "rules"} busy={busy} onFinish={finish} />
          ) : null}

          {step === "finishing" ? (
            <ChatBubble role="copilot" name={APP_NAME}>
              <StageLine initial="Running my first checks and writing your brief…" />
            </ChatBubble>
          ) : null}

          {step === "done" && finished ? (
            <ChatBubble
              role="copilot"
              name={APP_NAME}
              attachment={
                <div className="ka-attach">
                  {finished.todo.length ? (
                    <Card padding="md" eyebrow="Your next steps">
                      <ol className="ka-onb__todo">
                        {finished.todo.map((t) => (
                          <li key={t}>{t}</li>
                        ))}
                      </ol>
                    </Card>
                  ) : null}
                  {finished.could_also_check.map((h) => (
                    <p key={h} className="kc-caption">
                      {h}
                    </p>
                  ))}
                  <div>
                    <Button iconRight={ArrowRight} onClick={openApp}>
                      Open my first brief
                    </Button>
                  </div>
                </div>
              }
            >
              All set. I have already looked through everything and written your first Morning Brief.
            </ChatBubble>
          ) : null}

          {error ? (
            <p className="ka-onb__error" role="alert">
              <CircleAlert size={16} strokeWidth={1.5} aria-hidden /> {error}
            </p>
          ) : null}
          <div ref={end} />
        </div>
      </div>
    </div>
  );
}

function Owner({ text }: { text?: string }) {
  return text ? <ChatBubble role="owner">{text}</ChatBubble> : null;
}

function TextAsk({ placeholder, onSubmit }: { placeholder: string; onSubmit: (v: string) => void }) {
  const [v, setV] = useState("");
  return (
    <form
      className="ka-compose"
      onSubmit={(e) => {
        e.preventDefault();
        if (v.trim()) onSubmit(v.trim());
      }}
    >
      <input
        value={v}
        onChange={(e) => setV(e.target.value)}
        placeholder={placeholder}
        aria-label={placeholder}
        autoFocus
      />
      <Button type="submit" size="sm" iconLeft={ArrowRight} aria-label="Continue" disabled={!v.trim()} />
    </form>
  );
}

function Chips({ options, onPick, disabled }: { options: string[]; onPick: (v: string) => void; disabled?: boolean }) {
  return (
    <div className="ka-sugg ka-onb__chips">
      {options.map((o) => (
        <button key={o} type="button" className="ka-chip" disabled={disabled} onClick={() => onPick(o)}>
          {o}
        </button>
      ))}
    </div>
  );
}

function CashAsk({
  currency,
  busy,
  onSubmit,
}: {
  currency: string;
  busy: boolean;
  onSubmit: (minor: number | null, text: string) => void;
}) {
  const [v, setV] = useState("");
  const minor = toMinor(v);
  return (
    <div className="ka-stack" style={{ gap: 8 }}>
      <form
        className="ka-compose"
        onSubmit={(e) => {
          e.preventDefault();
          if (minor !== null) onSubmit(minor, money(minor, currency));
        }}
      >
        <input
          value={v}
          onChange={(e) => setV(e.target.value)}
          placeholder={`Cash on hand (${currency})`}
          aria-label="Cash on hand"
          inputMode="decimal"
          autoFocus
        />
        <Button
          type="submit"
          size="sm"
          iconLeft={ArrowRight}
          aria-label="Continue"
          loading={busy}
          disabled={minor === null}
        />
      </form>
      <div>
        <Button variant="ghost" size="sm" onClick={() => onSubmit(null, "I am not sure, skip it")}>
          Not sure, skip
        </Button>
      </div>
    </div>
  );
}

function BillsAsk({ currency, busy, onSubmit }: { currency: string; busy: boolean; onSubmit: (b: Bill[]) => void }) {
  const [rows, setRows] = useState<{ name: string; amount: string; day: string; kind: "bill" | "loan" }[]>([
    { name: "", amount: "", day: "1", kind: "bill" },
  ]);
  const set = (i: number, patch: Partial<(typeof rows)[number]>) =>
    setRows((r) => r.map((x, j) => (j === i ? { ...x, ...patch } : x)));
  const bills: Bill[] = rows
    .filter((r) => r.name.trim() && toMinor(r.amount))
    .map((r) => ({
      name: r.name.trim(),
      kind: r.kind,
      amount_minor: toMinor(r.amount)!,
      day_of_month: Math.min(28, Math.max(1, parseInt(r.day, 10) || 1)),
    }));
  return (
    <div className="ka-stack" style={{ gap: 8 }}>
      {rows.map((r, i) => (
        <div key={i} className="ka-onb__bill">
          <input
            value={r.name}
            onChange={(e) => set(i, { name: e.target.value })}
            placeholder="Paid to, e.g. City Power"
            aria-label="Paid to"
          />
          <input
            value={r.amount}
            onChange={(e) => set(i, { amount: e.target.value })}
            placeholder={`Amount (${currency})`}
            aria-label="Amount"
            inputMode="decimal"
          />
          <input
            value={r.day}
            onChange={(e) => set(i, { day: e.target.value })}
            aria-label="Day of the month it is due"
            inputMode="numeric"
            title="Day of the month"
          />
          <select
            value={r.kind}
            onChange={(e) => set(i, { kind: e.target.value as "bill" | "loan" })}
            aria-label="Bill or loan"
          >
            <option value="bill">Bill</option>
            <option value="loan">Loan</option>
          </select>
          <button
            type="button"
            className="ka-ibtn"
            aria-label="Remove"
            onClick={() => setRows((x) => x.filter((_, j) => j !== i))}
          >
            <Trash2 size={16} strokeWidth={1.5} />
          </button>
        </div>
      ))}
      <div className="ka-onb__row">
        <Button
          variant="ghost"
          size="sm"
          iconLeft={Plus}
          onClick={() => setRows((x) => [...x, { name: "", amount: "", day: "1", kind: "bill" }])}
        >
          Add another
        </Button>
        <Button size="sm" loading={busy} disabled={!bills.length} onClick={() => onSubmit(bills)}>
          Save {bills.length || ""} {bills.length === 1 ? "bill" : "bills"}
        </Button>
        <Button variant="ghost" size="sm" onClick={() => onSubmit([])}>
          None, skip
        </Button>
      </div>
    </div>
  );
}

function Questions({
  view,
  active,
  busy,
  said,
  onAnswer,
}: {
  view: OnboardingView;
  active: boolean;
  busy: boolean;
  said: Partial<Record<string, string>>;
  onAnswer: (qid: string, option: number, label: string) => void;
}) {
  const questions = view.plan.questions;
  const current = questions.findIndex((q) => !said[`q:${q.id}`]);
  const shown = active
    ? questions.slice(0, current < 0 ? questions.length : current + 1)
    : questions.filter((q) => said[`q:${q.id}`]);
  return (
    <>
      {active && current === 0 ? (
        <ChatBubble role="copilot" name={APP_NAME}>
          A few questions an experienced {view.plan.pack_name.toLowerCase()} advisor would ask. Owners often do not
          think of these, and each one changes what I check for you.
        </ChatBubble>
      ) : null}
      {shown.map((q) => (
        <div key={q.id} className="ka-stack" style={{ gap: 12 }}>
          <ChatBubble role="copilot" name={APP_NAME}>
            {q.ask}
            <span className="ka-onb__why">Why I am asking: {q.why}</span>
          </ChatBubble>
          {said[`q:${q.id}`] ? (
            <Owner text={said[`q:${q.id}`]} />
          ) : (
            <Chips
              options={q.options.map((o) => o.label)}
              disabled={busy}
              onPick={(label) =>
                onAnswer(
                  q.id,
                  q.options.findIndex((o) => o.label === label),
                  label,
                )
              }
            />
          )}
        </div>
      ))}
    </>
  );
}

function Needs({
  id,
  view,
  currency,
  active,
  onView,
  onDone,
}: {
  id: string;
  view: OnboardingView;
  currency: string;
  active: boolean;
  onView: (v: OnboardingView) => void;
  onDone: () => void;
}) {
  const [results, setResults] = useState<UploadResult[]>([]);
  const [uploading, setUploading] = useState<string | null>(null);
  const [drag, setDrag] = useState(false);
  const picker = useRef<HTMLInputElement>(null);
  const skipped = view.state.skipped ?? [];
  const imported = new Set(results.filter((r) => r.status === "imported").map((r) => r.kind));
  const open = view.plan.data_needs.filter((n) => !imported.has(n.kind) && !skipped.includes(n.id));
  const current: DataNeed | undefined = open[0];
  const asked = view.plan.data_needs.filter((n) => imported.has(n.kind) || skipped.includes(n.id) || n === current);

  const send = async (files: File[]) => {
    for (const f of [...files].sort((a, b) => uploadRank(a) - uploadRank(b))) {
      setUploading(f.name);
      try {
        const r = await api.uploadOnboardingFile(id, f);
        setResults((x) => [...x, r]);
      } catch (e) {
        setResults((x) => [
          ...x,
          {
            filename: f.name,
            kind: "unknown",
            status: "rejected",
            message: errorMessage(e),
          },
        ]);
      }
    }
    setUploading(null);
    onView(await api.onboarding(id));
  };

  const skip = async (need: DataNeed) => onView(await api.skipNeed(id, { need_id: need.id }));

  return (
    <>
      <ChatBubble role="copilot" name={APP_NAME}>
        Now your files. Drop them all at once if you like, and I will work out what each one is.
      </ChatBubble>
      {asked.map((n) => (
        <ChatBubble key={n.id} role="copilot" name={APP_NAME}>
          {n.ask}
          <span className="ka-onb__why">Why I am asking: {n.why}</span>
          {skipped.includes(n.id) ? <span className="kc-caption"> Skipped; you can add it later.</span> : null}
          {imported.has(n.kind) ? (
            <span className="ka-onb__ok">
              <CircleCheck size={16} strokeWidth={1.5} aria-hidden /> Got it.
            </span>
          ) : null}
          {active && n === current ? (
            <span className="ka-onb__row" style={{ marginTop: 10 }}>
              <Button size="sm" variant="secondary" iconLeft={Upload} onClick={() => picker.current?.click()}>
                Upload file
              </Button>
              <Button size="sm" variant="ghost" onClick={() => skip(n)}>
                Skip
              </Button>
            </span>
          ) : null}
        </ChatBubble>
      ))}
      {active ? (
        <label
          className={cn("ka-drop", drag && "is-drag")}
          onDragOver={(e) => {
            e.preventDefault();
            setDrag(true);
          }}
          onDragLeave={() => setDrag(false)}
          onDrop={(e) => {
            e.preventDefault();
            setDrag(false);
            void send(Array.from(e.dataTransfer.files));
          }}
        >
          <FileUp size={22} strokeWidth={1.5} aria-hidden />
          <span>
            {uploading ? `Reading ${uploading}…` : "Drop files here, or click to choose"}
            <span className="kc-caption">CSV (bank, products, sales, ad spend), PDF invoices, receipt photos</span>
          </span>
          <input
            ref={picker}
            type="file"
            multiple
            accept=".csv,.pdf,.png,.jpg,.jpeg,.webp"
            hidden
            onChange={(e) => {
              const files = Array.from(e.target.files ?? []);
              e.target.value = "";
              void send(files);
            }}
          />
        </label>
      ) : null}
      {results.length ? (
        <div className="ka-attach">
          {results.map((r, i) => (
            <UploadCard key={`${r.filename}-${i}`} id={id} result={r} currency={currency} />
          ))}
        </div>
      ) : null}
      {active ? (
        <div className="ka-onb__row">
          <Button iconRight={ArrowRight} disabled={!!uploading} onClick={onDone}>
            {open.length ? "Continue without the rest" : "Continue"}
          </Button>
        </div>
      ) : null}
    </>
  );
}

function UploadCard({ id, result: r, currency }: { id: string; result: UploadResult; currency: string }) {
  const [doc, setDoc] = useState<InboxRecord | null>(null);
  const [approved, setApproved] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => {
    if (r.document_id) api.onboardingDocument(id, r.document_id).then(setDoc, () => {});
  }, [id, r.document_id]);

  const amount = doc?.fields.amount_minor?.value;
  const who = doc?.owner_view.supplier_name || doc?.owner_view.merchant_name || doc?.owner_view.payee_name;
  const status =
    r.status === "imported" || approved ? "executed" : r.status === "pending_review" ? "waiting" : "blocked";
  const pillLabel =
    r.status === "imported"
      ? "Imported"
      : r.status === "pending_review"
        ? approved
          ? "Approved"
          : "Needs your OK"
        : r.status === "flagged"
          ? "Held"
          : "Rejected";

  if (r.status === "flagged") {
    const flags = doc?.sentinel.flags ?? [];
    return (
      <div className="ka-onb__file is-flagged">
        <ShieldAlert size={18} strokeWidth={1.5} aria-hidden className="i" />
        <div className="w">
          <div className="t">
            {r.filename} <Badge variant="neutral">{KIND_LABEL[r.kind]}</Badge>
          </div>
          <span className="kc-caption">
            {flags.length ? flags.map((f) => flagLabel(f.code)).join(". ") + ". " : ""}
            {r.message}
          </span>
        </div>
        <StatusPill status="blocked" size="sm" label="Held" />
      </div>
    );
  }
  return (
    <div className="ka-onb__file">
      <CircleCheck size={18} strokeWidth={1.5} aria-hidden className="i" />
      <div className="w">
        <div className="t">
          {r.filename} <Badge variant="neutral">{KIND_LABEL[r.kind]}</Badge>
        </div>
        {r.status === "imported" ? (
          <span className="kc-caption">
            {r.rows} rows{r.added !== r.rows ? `, ${r.added} new` : ""}
            {r.duplicates ? `, ${r.duplicates} already there` : ""}
            {r.date_from ? `, ${r.date_from} to ${r.date_to}` : ""}
            {r.ignored_columns?.length ? `. Ignored columns: ${r.ignored_columns.join(", ")}` : ""}
          </span>
        ) : r.status === "rejected" ? (
          <span className="kc-caption">
            {r.message}{" "}
            {r.errors
              ?.slice(0, 4)
              .map((e) => `Line ${e.line}: ${e.message}.`)
              .join(" ")}
            {(r.errors?.length ?? 0) > 4 ? ` And ${(r.errors?.length ?? 0) - 4} more.` : ""}
          </span>
        ) : (
          <span className="kc-caption">
            {who ? `${who}: ` : ""}
            {amount ? money(amount, currency) : ""}
            {amount ? ". " : ""}
            {approved ? "Approved. I will plan for it." : r.message}
            {err ? ` ${err}` : ""}
          </span>
        )}
        {r.status === "pending_review" && amount && !approved ? (
          <div style={{ marginTop: 8 }}>
            <Button
              size="sm"
              variant="secondary"
              loading={busy}
              onClick={async () => {
                setBusy(true);
                try {
                  await api.approveDocument(id, r.document_id!);
                  setApproved(true);
                } catch (e) {
                  setErr(errorMessage(e));
                } finally {
                  setBusy(false);
                }
              }}
            >
              Approve this amount
            </Button>
          </div>
        ) : null}
      </div>
      <StatusPill status={status} size="sm" label={pillLabel} />
    </div>
  );
}

function ContactsStep({
  view,
  active,
  busy,
  onConfirm,
  said,
}: {
  view: OnboardingView;
  active: boolean;
  busy: boolean;
  onConfirm: (c: ContactIn[]) => void;
  said?: string;
}) {
  const proposals = view.contacts.filter((c) => c.source !== "bill");
  const [chosen, setChosen] = useState<Record<string, boolean>>(() =>
    Object.fromEntries(proposals.map((c) => [c.id, c.confirmed || c.source === "document" || c.seen >= 2])),
  );
  if (!proposals.length) {
    return active ? (
      <>
        <ChatBubble role="copilot" name={APP_NAME}>
          I did not find suppliers or customers in your files yet. You can add them later.
        </ChatBubble>
        <div className="ka-onb__row">
          <Button iconRight={ArrowRight} onClick={() => onConfirm([])}>
            Continue
          </Button>
        </div>
      </>
    ) : (
      <Owner text={said} />
    );
  }
  return (
    <>
      <ChatBubble
        role="copilot"
        name={APP_NAME}
        attachment={
          active ? (
            <Card padding="md" eyebrow="Known contacts">
              <ul className="ka-foldlist ka-insights">
                {proposals.map((c) => (
                  <li key={c.id}>
                    <label className="ka-onb__check">
                      <input
                        type="checkbox"
                        checked={!!chosen[c.id]}
                        onChange={(e) => setChosen((x) => ({ ...x, [c.id]: e.target.checked }))}
                      />
                      <span className="w">
                        <span>{c.name}</span>
                        <span className="kc-caption">
                          {c.kind === "customer" ? "Customer" : c.kind === "payee" ? "Regular bill" : "Supplier"} · from
                          your {c.source === "document" ? "invoices" : "statement"}
                        </span>
                      </span>
                    </label>
                  </li>
                ))}
              </ul>
            </Card>
          ) : null
        }
      >
        These are the businesses your files say you deal with. Tick the ones you know. I will treat anyone else as a
        stranger, which is how I catch fake suppliers and changed bank details.
      </ChatBubble>
      {active ? (
        <div className="ka-onb__row">
          <Button
            iconLeft={CircleCheck}
            loading={busy}
            onClick={() =>
              onConfirm(
                proposals
                  .filter((c) => chosen[c.id])
                  .map((c) => ({
                    name: c.name,
                    kind: c.kind,
                    domain: c.domain,
                  })),
              )
            }
          >
            Confirm contacts
          </Button>
        </div>
      ) : (
        <Owner text={said} />
      )}
    </>
  );
}

function Rules({
  id,
  view,
  active,
  busy,
  onFinish,
}: {
  id: string;
  view: OnboardingView;
  active: boolean;
  busy: boolean;
  onFinish: () => void;
}) {
  const [state, setState] = useState<Record<string, "signed" | "skipped">>({});
  const open = view.mandates.filter((m) => !state[m.tool]);
  return (
    <>
      <ChatBubble role="copilot" name={APP_NAME}>
        {view.mandates.length
          ? "One last thing: limits. Within a limit you sign, I act on my own; anything above it waits for you. Here is a starting point from your data. Sign it, or skip it for now."
          : "Limits come next: within a limit you sign I act on my own. I do not have enough regular bills yet to suggest one, so we can set limits later."}
      </ChatBubble>
      {view.mandates.map((m) => (
        <MandateCard
          key={m.tool}
          id={id}
          mandate={m}
          view={view}
          state={state[m.tool]}
          onDone={(s) => setState((x) => ({ ...x, [m.tool]: s }))}
        />
      ))}
      {active ? (
        <div className="ka-onb__row">
          <Button iconRight={ArrowRight} loading={busy} onClick={onFinish}>
            {open.length ? "Skip and finish" : "Finish and show my brief"}
          </Button>
        </div>
      ) : null}
    </>
  );
}

function MandateCard({
  id,
  mandate: m,
  view,
  state,
  onDone,
}: {
  id: string;
  mandate: SuggestedMandate;
  view: OnboardingView;
  state?: "signed" | "skipped";
  onDone: (s: "signed" | "skipped") => void;
}) {
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const sign = async () => {
    setBusy(true);
    setErr(null);
    try {
      const draft = await api.draftMandate(id, {
        action: m.tool,
        terms: { max_amount_minor: m.max_amount_minor, allowlist: m.allowlist },
        days: MANDATE_DAYS,
      });
      await ensureEnrolled(id);
      const { signature, publicKey } = await signMessage(draft.message);
      const r = await api.signMandate(id, {
        payload: draft.payload,
        terms: draft.terms,
        signature,
        public_key: publicKey,
      });
      if (r.accepted) onDone("signed");
      else setErr(`The gateway refused it: ${r.rule ?? "denied"}.`);
    } catch (e) {
      setErr(errorMessage(e));
    } finally {
      setBusy(false);
    }
  };
  return (
    <Card
      padding="md"
      eyebrow="Suggested limit"
      title={m.title}
      description={<FactText text={m.text} facts={view.facts} />}
      action={
        state ? (
          <StatusPill
            status={state === "signed" ? "executed" : "neutral"}
            size="sm"
            label={state === "signed" ? "Signed" : "Skipped"}
          />
        ) : null
      }
      footer={
        state ? null : (
          <div className="ka-improve-foot">
            <Button size="sm" iconLeft={PenLine} loading={busy} onClick={sign}>
              Sign this limit
            </Button>
            <Button size="sm" variant="ghost" onClick={() => onDone("skipped")}>
              Skip
            </Button>
            {err ? <span className="kc-caption">{err}</span> : null}
          </div>
        )
      }
    >
      <span className="kc-caption">
        Lasts {MANDATE_DAYS} days. Signed with the key in this browser; you can lower or end it any time.
      </span>
    </Card>
  );
}
