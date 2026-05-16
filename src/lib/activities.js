const files = import.meta.glob('../../data/activities/*.json', { eager: true });

const activities = Object.values(files)
  .map((m) => m.default)
  .sort((a, b) => (b.date > a.date ? 1 : -1));

export default activities;
