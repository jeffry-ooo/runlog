import rss from '@astrojs/rss';
import activities from '../lib/activities.js';

export function GET(context) {
  return rss({
    title: 'JEFFRY.RUNNING',
    description: 'A one-way running logbook. Antwerp-based. Trail runner. Goal: 50K — 01.11.2026.',
    site: context.site,
    items: activities.map((a) => {
      const dist = (a.distance_m / 1000).toFixed(1);
      const day = new Date(a.date).toLocaleDateString('en-GB', {
        day: 'numeric', month: 'short', timeZone: a.timezone,
      }).toUpperCase();
      const beers = Math.round((a.calories || 0) / 200);
      return {
        title: `${day} — ${dist}KM`,
        description: `Effort: ${a.effort} | Avg HR: ${a.heartrate_avg}BPM | Beers earned: ${beers}`,
        link: `${import.meta.env.BASE_URL}run/${a.id}`,
        pubDate: new Date(a.date),
      };
    }),
  });
}
