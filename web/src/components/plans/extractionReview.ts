import type {
  DraftReviewIssue,
  PlanExtractionView,
  ReviewIssueKind,
} from "../../api/generated";

export interface ExtractionReviewItem {
  readonly excerpt?: string;
  readonly issue: DraftReviewIssue;
  readonly key: string;
  readonly message: string;
}

export function extractionReviewItems(
  extraction: PlanExtractionView,
): readonly ExtractionReviewItem[] {
  const items: ExtractionReviewItem[] = [];
  for (const issue of extraction.assumptions ?? []) {
    items.push(reviewItem("ASSUMPTION", issue.path, issue.material, issue.message));
  }
  for (const issue of extraction.warnings ?? []) {
    items.push(reviewItem("WARNING", issue.path, issue.material, issue.message));
  }
  for (const issue of extraction.unmappedText ?? []) {
    items.push(
      reviewItem("UNMAPPED_TEXT", issue.path, issue.material, issue.reason, issue.excerpt),
    );
  }
  for (const issue of extraction.validationIssues ?? []) {
    if (issue.code === "AI_EVIDENCE_REVIEW_REQUIRED" && issue.activationBlocking) {
      items.push(reviewItem("MISSING_EVIDENCE", issue.path, true, issue.message));
    }
  }
  return Object.freeze(items);
}

export function resolvedExtractionReviewIssues(
  extraction: PlanExtractionView,
  resolvedIssueKeys: readonly string[],
): readonly DraftReviewIssue[] {
  const items = extractionReviewItems(extraction);
  const duplicateKeys = duplicateReviewKeys(items);
  return Object.freeze(
    items.map(({ issue, key }) =>
      Object.freeze({
        ...issue,
        resolved: !duplicateKeys.has(key) && resolvedIssueKeys.includes(key),
      }),
    ),
  );
}

export function duplicateReviewKeys(
  items: readonly ExtractionReviewItem[],
): ReadonlySet<string> {
  const counts = new Map<string, number>();
  for (const item of items) {
    counts.set(item.key, (counts.get(item.key) ?? 0) + 1);
  }
  return new Set(
    [...counts.entries()].filter(([, count]) => count > 1).map(([key]) => key),
  );
}

export function reviewIssueKey(issue: DraftReviewIssue): string {
  return `${issue.kind}:${issue.path}`;
}

function reviewItem(
  kind: ReviewIssueKind,
  path: string,
  material: boolean,
  message: string,
  excerpt?: string,
): ExtractionReviewItem {
  const issue = Object.freeze({ kind, material, path, resolved: false });
  return Object.freeze({
    ...(excerpt === undefined ? {} : { excerpt }),
    issue,
    key: reviewIssueKey(issue),
    message,
  });
}
