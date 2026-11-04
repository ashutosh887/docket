export interface Criterion {
  id: string;
  points: number;
  max: number;
  readerA: number;
  readerB: number;
  margin: number;
  decidedBy: "code" | "teacher";
}

export interface Signature {
  alg: string;
  keyId: string;
  value: string;
}

export interface Credential {
  credentialId: string;
  scriptId: string;
  imageSha256: string;
  schemeId: string;
  schemeVersion: string;
  criteria: Criterion[];
  total: number;
  max: number;
  readers: { a: string; b: string };
  teacher: { decided: string[]; note: string | null };
  issuedAt: string;
  supersedes: string | null;
  route?: "straight" | "teacher";
  signature: Signature;
}

export interface RevocationEntry {
  credentialId: string;
  status: "superseded" | "revoked";
  reason: string;
  replacedBy: string | null;
}

export interface RevocationList {
  issuedAt: string;
  entries: RevocationEntry[];
  signature: Signature;
}

export interface SchemeCriterion {
  id: string;
  max?: number;
  text?: string;
  description?: string;
  title?: string;
}

export interface Scheme {
  schemeId: string;
  schemeVersion: string;
  previousVersion?: string | null;
  changedCriteria?: string[];
  note?: string;
  criteria: SchemeCriterion[];
}

export interface SiteIndex {
  source: "fixture" | "examples";
  generatedAt: string;
  credentials: { file: string; credentialId: string; scriptId: string; schemeVersion: string }[];
  revocations: string | null;
  schemes: { file: string; schemeId: string; schemeVersion: string }[];
  images: Record<string, string>;
  readings: Record<string, string[]>;
  pending?: string[];
}

export interface PendingReading {
  met?: boolean;
  confidence?: number;
  evidence?: string;
}

export interface Pending {
  scriptId: string;
  schemeVersion: string;
  interrupt?: {
    name: string;
    reason?: {
      contested: { id: string; criterion?: string; readerA: number; readerB: number; margin: number; why?: string; readings?: { a?: PendingReading; b?: PendingReading } }[];
    };
  };
  decisions?: Record<string, number>;
}

export interface SiteData {
  index: SiteIndex;
  key: CryptoKey;
  credentials: Map<string, { file: string; raw: string; doc: Credential }>;
  revocations: { list: RevocationList | null; valid: boolean };
  schemes: Scheme[];
  readings: Record<string, unknown[]>;
  pending: Pending[];
  evidence: Record<string, Record<"a" | "b", Record<string, { evidence?: string; confidence?: number; met?: boolean }>>>;
}
