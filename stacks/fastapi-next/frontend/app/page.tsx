// {{ project_name }} — home page (skeleton).
// Fetches the example endpoint through the same-origin /api proxy.

type Item = { id: number; name: string };

async function getItems(): Promise<Item[]> {
  try {
    const res = await fetch("http://backend:8000/api/items", {
      cache: "no-store",
    });
    const data = await res.json();
    return data.items ?? [];
  } catch {
    return [];
  }
}

export default async function Home() {
  const items = await getItems();
  return (
    <main style={{ fontFamily: "system-ui", padding: "2rem" }}>
      <h1>{{ project_name }}</h1>
      <p>{{ project_tagline }}</p>
      <h2>Items</h2>
      <ul data-testid="items">
        {items.map((it) => (
          <li key={it.id}>{it.name}</li>
        ))}
      </ul>
    </main>
  );
}
