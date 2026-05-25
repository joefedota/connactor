import type { DailyHistoryResponse } from '../../types';
import './DailyHistory.css';

interface Props {
  data: DailyHistoryResponse;
}

const BUCKETS: { key: keyof DailyHistoryResponse; label: string }[] = [
  { key: 'bucket_1', label: '1 actor' },
  { key: 'bucket_2', label: '2 actors' },
  { key: 'bucket_3', label: '3 actors' },
  { key: 'bucket_4', label: '4 actors' },
  { key: 'bucket_5', label: '5 actors' },
  { key: 'bucket_6_plus', label: '6+ actors' },
];

export function DailyHistory({ data }: Props) {
  if (!data.entries.length) return null;

  const maxBucket = Math.max(
    ...BUCKETS.map((b) => (data[b.key] as number)),
    1,
  );

  return (
    <div className="daily-history">
      <div className="daily-history__section-label">Your history</div>

      {/* Bar chart */}
      <div className="daily-history__chart">
        {BUCKETS.map(({ key, label }) => {
          const count = data[key] as number;
          const pct = Math.round((count / maxBucket) * 100);
          return (
            <div key={key} className="daily-history__bar-row">
              <span className="daily-history__bar-label">{label}</span>
              <div className="daily-history__bar-track">
                <div
                  className="daily-history__bar-fill"
                  style={{ width: count === 0 ? '0%' : `${Math.max(pct, 4)}%` }}
                />
              </div>
              <span className="daily-history__bar-count">{count}</span>
            </div>
          );
        })}
      </div>

    </div>
  );
}
