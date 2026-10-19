"use client";

import { ArrowLeft, CircleAlert, CircleCheck, FileUp, ShieldAlert, ShieldCheck } from "lucide-react";
import { Fragment, useEffect, useState } from "react";

import { Badge } from "@/components/kc/badge";
import { Button } from "@/components/kc/button";
import { Card } from "@/components/kc/card";
import { APP_NAME } from "@/config/app";
import { api } from "@/lib/api";
import { errorMessage } from "@/lib/errors";
import type { SkillPreview } from "@/lib/types";
import { cn } from "@/lib/utils";

export type SkillChoice = { name: string; pack_id?: string; skill_sha256?: string };

const MAX_SKILL_BYTES = 64 * 1024;

/** The trust badge: signed by the library key, or a community skill nobody vouched for. */
export function SkillBadge({ badge }: { badge: SkillPreview["badge"] }) {
  return badge === "verified" ? (
    <Badge variant="brand" icon={ShieldCheck}>
      Verified
    </Badge>
  ) : (
    <Badge variant="outline" icon={ShieldAlert}>
      Community — unverified
    </Badge>
  );
}

/** First paragraph of a skill's description, without its heading. */
function blurb(md: string | undefined): string {
  const paras = (md ?? "").split(/\n\s*\n/).map((p) => p.trim());
  return (paras.find((p) => p && !p.startsWith("#")) ?? "").replace(/\s+/g, " ");
}

/**
 * Opening step of onboarding (feature plan P8): pick a built-in skill or upload your own skill.md. An upload is
 * validated by the server and previewed here (what it asks, what it watches, its trust badge) before it is used.
 */
export function SkillPicker({ disabled, onPick }: { disabled?: boolean; onPick: (c: SkillChoice) => void }) {
  const [builtins, setBuiltins] = useState<SkillPreview[]>([]);
  const [preview, setPreview] = useState<SkillPreview | null>(null);
  const [uploading, setUploading] = useState<string | null>(null);
  const [drag, setDrag] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.skills().then(setBuiltins, (e) => setError(errorMessage(e)));
  }, []);

  const send = async (file: File | undefined) => {
    if (!file) return;
    setError(null);
    setPreview(null);
    if (file.size > MAX_SKILL_BYTES) {
      setPreview({ status: "rejected", filename: file.name, errors: ["the file is larger than 64 KB"] });
      return;
    }
    setUploading(file.name);
    try {
      setPreview(await api.previewSkill(file));
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setUploading(null);
    }
  };

  if (preview) {
    return (
      <SkillPreviewCard
        preview={preview}
        disabled={disabled}
        onBack={() => setPreview(null)}
        onUse={() =>
          onPick({
            name: preview.display_name ?? "Custom skill",
            ...(preview.builtin && preview.pack_id ? { pack_id: preview.pack_id } : { skill_sha256: preview.sha256! }),
          })
        }
      />
    );
  }

  return (
    <div className="ka-skills">
      <div className="ka-skills__grid">
        {builtins.map((s) => (
          <button
            key={s.pack_id}
            type="button"
            className="ka-skill"
            disabled={disabled}
            onClick={() => onPick({ name: s.display_name ?? "", pack_id: s.pack_id! })}
          >
            <span className="ka-skill__head">
              <span className="ka-skill__name">{s.display_name}</span>
              <SkillBadge badge={s.badge} />
            </span>
            <span className="ka-skill__blurb">{blurb(s.description)}</span>
          </button>
        ))}
        <label
          className={cn("ka-skill ka-skill--upload", drag && "is-drag")}
          onDragOver={(e) => {
            e.preventDefault();
            setDrag(true);
          }}
          onDragLeave={() => setDrag(false)}
          onDrop={(e) => {
            e.preventDefault();
            setDrag(false);
            void send(e.dataTransfer.files[0]);
          }}
        >
          <span className="ka-skill__head">
            <span className="ka-skill__name">
              <FileUp size={18} strokeWidth={1.5} aria-hidden /> Upload your own skill.md
            </span>
          </span>
          <span className="ka-skill__blurb">
            {uploading
              ? `Checking ${uploading}…`
              : `Anyone can teach ${APP_NAME} a new kind of business. I check the file and show you what it does before I use it.`}
          </span>
          <input
            type="file"
            accept=".md,text/markdown"
            hidden
            disabled={disabled || !!uploading}
            onChange={(e) => {
              const f = e.target.files?.[0];
              e.target.value = "";
              void send(f);
            }}
          />
        </label>
      </div>
      {error ? (
        <p className="ka-onb__error" role="alert">
          <CircleAlert size={16} strokeWidth={1.5} aria-hidden /> {error}
        </p>
      ) : null}
    </div>
  );
}

function SkillPreviewCard({
  preview: p,
  disabled,
  onUse,
  onBack,
}: {
  preview: SkillPreview;
  disabled?: boolean;
  onUse: () => void;
  onBack: () => void;
}) {
  if (p.status === "rejected") {
    return (
      <Card
        padding="md"
        eyebrow="Skill check"
        title={`I could not use ${p.filename ?? "this file"}`}
        description="Nothing was activated. Fix these and upload it again:"
        footer={
          <Button variant="secondary" iconLeft={ArrowLeft} onClick={onBack}>
            Choose another
          </Button>
        }
        className="ka-skillprev is-rejected"
      >
        <ul className="ka-skillprev__errors">
          {(p.errors ?? []).map((e, i) => (
            <li key={i}>
              <code>{e}</code>
            </li>
          ))}
        </ul>
      </Card>
    );
  }
  const required = (p.data_needs ?? []).filter((n) => n.required);
  const optional = (p.data_needs ?? []).filter((n) => !n.required);
  return (
    <Card
      padding="md"
      eyebrow="Skill preview"
      title={p.display_name}
      action={<SkillBadge badge={p.badge} />}
      description={`${p.filename ?? "skill.md"} · version ${p.version} · sha256 ${p.sha256?.slice(0, 12)}…`}
      className="ka-skillprev"
      footer={
        <div className="ka-onb__row">
          <Button iconLeft={CircleCheck} disabled={disabled} onClick={onUse}>
            Use this skill
          </Button>
          <Button variant="ghost" iconLeft={ArrowLeft} onClick={onBack}>
            Choose another
          </Button>
        </div>
      }
    >
      <div className="ka-skillprev__body">
        <p className={cn("ka-skillprev__trust", p.badge !== "verified" && "is-community")}>
          {p.badge === "verified" ? (
            <>
              <ShieldCheck size={16} strokeWidth={1.5} aria-hidden /> Signed by the {APP_NAME} skill library.
            </>
          ) : (
            <>
              <ShieldAlert size={16} strokeWidth={1.5} aria-hidden /> Not signed by the {APP_NAME} library. It can only
              set up built-in checks: it cannot add code, change your limits or move money, and its text never reaches
              my planner.
            </>
          )}
        </p>
        {(p.notices ?? []).map((n) => (
          <p key={n} className="ka-skillprev__notice">
            <CircleAlert size={16} strokeWidth={1.5} aria-hidden /> {n}
          </p>
        ))}

        <section>
          <h4 className="kc-caption ka-skillprev__h">About this skill</h4>
          <div className="ka-md">
            <SafeMarkdown text={p.description ?? ""} />
          </div>
        </section>

        <section>
          <h4 className="kc-caption ka-skillprev__h">What I will ask you</h4>
          <ul className="ka-skillprev__list">
            {required.map((n) => (
              <li key={n.id}>
                {n.ask} <Badge variant="neutral">Needed</Badge>
              </li>
            ))}
            {optional.map((n) => (
              <li key={n.id}>
                {n.ask} <Badge variant="outline">Optional</Badge>
              </li>
            ))}
            {(p.questions ?? []).map((q) => (
              <li key={q.id}>
                {q.ask}
                <span className="ka-onb__why">Why I am asking: {q.why}</span>
              </li>
            ))}
          </ul>
        </section>

        <section>
          <h4 className="kc-caption ka-skillprev__h">What I will watch</h4>
          <ul className="ka-skillprev__list">
            {(p.detectors ?? []).map((d) => (
              <li key={d.detector}>{d.label}</li>
            ))}
          </ul>
          {p.kpis?.length ? (
            <div className="ka-skillprev__kpis">
              {p.kpis.map((k) => (
                <Badge key={k.id} variant="outline">
                  {k.label}
                </Badge>
              ))}
            </div>
          ) : null}
        </section>
      </div>
    </Card>
  );
}

/** Inline Markdown: **bold**, *italic*, `code`; a [link](url) shows its text only. Built from text nodes, never HTML. */
function inline(text: string): React.ReactNode[] {
  const out: React.ReactNode[] = [];
  const rx = /(\*\*[^*]+\*\*|`[^`]+`|\*[^*\s][^*]*\*|_[^_\s][^_]*_|\[[^\]]+\]\([^)]*\))/g;
  let last = 0;
  let k = 0;
  for (const m of text.matchAll(rx)) {
    const t = m[0];
    if (m.index! > last) out.push(text.slice(last, m.index));
    if (t.startsWith("**")) out.push(<strong key={k++}>{t.slice(2, -2)}</strong>);
    else if (t.startsWith("`")) out.push(<code key={k++}>{t.slice(1, -1)}</code>);
    else if (t.startsWith("[")) out.push(t.slice(1, t.indexOf("]")));
    else out.push(<em key={k++}>{t.slice(1, -1)}</em>);
    last = m.index! + t.length;
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
}

/**
 * Safe Markdown for an uploaded skill's description (untrusted): headings, paragraphs and lists, rendered as React
 * text. No HTML is ever interpreted (no dangerouslySetInnerHTML), so a skill cannot run script in the page.
 */
export function SafeMarkdown({ text }: { text: string }) {
  const blocks: React.ReactNode[] = [];
  const st: { para: string[]; list: { ordered: boolean; items: string[] } | null } = { para: [], list: null };
  const flush = () => {
    if (st.para.length) blocks.push(<p key={blocks.length}>{inline(st.para.join(" "))}</p>);
    if (st.list) {
      const items = st.list.items.map((it, i) => <li key={i}>{inline(it)}</li>);
      blocks.push(st.list.ordered ? <ol key={blocks.length}>{items}</ol> : <ul key={blocks.length}>{items}</ul>);
    }
    st.para = [];
    st.list = null;
  };
  for (const raw of text.replace(/\r\n?/g, "\n").split("\n")) {
    const line = raw.trim();
    const heading = /^(#{1,6})\s+(.*)$/.exec(line);
    const item = /^(?:[-*+]|(\d+)[.)])\s+(.*)$/.exec(line);
    if (!line) {
      flush();
    } else if (heading) {
      flush();
      blocks.push(
        <p key={blocks.length} className={heading[1].length === 1 ? "ka-md__h1" : "ka-md__h2"}>
          {inline(heading[2])}
        </p>,
      );
    } else if (item) {
      const ordered = item[1] !== undefined;
      if (st.para.length || (st.list && st.list.ordered !== ordered)) flush();
      st.list ??= { ordered, items: [] };
      st.list.items.push(item[2]);
    } else if (st.list && raw.startsWith("  ")) {
      st.list.items[st.list.items.length - 1] += " " + line;
    } else {
      if (st.list) flush();
      st.para.push(line);
    }
  }
  flush();
  return <Fragment>{blocks}</Fragment>;
}
