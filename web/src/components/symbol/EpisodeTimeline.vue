<script setup lang="ts">
import { computed } from "vue";

import type { SymbolEventView } from "../../api/generated";
import { formatDisplayDateTime } from "../../formatters/dateTime";

interface Props {
  events: readonly SymbolEventView[];
  selectedAt: string | null;
}

interface Emits {
  selectTime: [occurredAt: string];
}

const props = defineProps<Props>();
const emit = defineEmits<Emits>();

const timelineEvents = computed<readonly SymbolEventView[]>(() =>
  Object.freeze(
    props.events
      .filter((event) => event.eventType === "EPISODE" || event.eventType === "RISK")
      .sort((left, right) =>
        left.occurredAt === right.occurredAt ? 0 : left.occurredAt < right.occurredAt ? -1 : 1,
      ),
  ),
);
</script>

<template>
  <section class="episode-timeline" aria-labelledby="episode-timeline-title">
    <h2 id="episode-timeline-title" class="episode-timeline__title">阶段与风险时间线</h2>
    <p v-if="timelineEvents.length === 0" class="episode-timeline__empty">暂无阶段或风险事件。</p>
    <ol v-else class="episode-timeline__list">
      <li v-for="event in timelineEvents" :key="event.eventId" class="episode-timeline__item">
        <button
          class="episode-timeline__button"
          type="button"
          :aria-current="selectedAt === event.occurredAt ? 'true' : undefined"
          @click="emit('selectTime', event.occurredAt)"
        >
          <span class="episode-timeline__type">{{ event.eventType }}</span>
          <time class="episode-timeline__time" :datetime="event.occurredAt">
            {{ formatDisplayDateTime(event.occurredAt) }}
          </time>
          <span class="episode-timeline__message">{{ event.messageText ?? "状态发生变化" }}</span>
        </button>
      </li>
    </ol>
  </section>
</template>

<style scoped>
.episode-timeline {
  padding: var(--space-4);
  background: var(--color-surface-graphite);
  border: var(--border-technical);
}

.episode-timeline__title {
  margin-block-start: 0;
}

.episode-timeline__empty {
  color: var(--color-text-muted);
}

.episode-timeline__list {
  display: grid;
  gap: var(--space-3);
  padding: 0;
  list-style: none;
}

.episode-timeline__item {
  border-inline-start: 0.25rem solid var(--color-signal-info-cyan);
}

.episode-timeline__button {
  display: grid;
  width: 100%;
  gap: var(--space-1);
  padding: var(--space-3);
  color: var(--color-text-mineral);
  text-align: start;
  background: var(--color-surface-raised);
  border: 0;
}

.episode-timeline__button[aria-current="true"] {
  outline: 0.125rem solid var(--color-signal-watch-amber);
  outline-offset: 0.125rem;
}

.episode-timeline__type,
.episode-timeline__time {
  font-family: var(--font-numeric);
  color: var(--color-text-muted);
}

.episode-timeline__message {
  overflow-wrap: anywhere;
}
</style>
