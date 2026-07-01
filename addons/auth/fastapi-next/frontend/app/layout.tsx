// Root layout (auth add-on): renders the sign-in widget in a header above every
// page. The widget is a client component; a server layout can render it directly.
import AuthWidget from "./auth-widget";

export const metadata = {
  title: "{{ project_name }}",
  description: "{{ project_tagline }}",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body>
        <header
          style={{
            display: "flex",
            justifyContent: "flex-end",
            padding: "0.75rem 1rem",
            borderBottom: "1px solid #eee",
          }}
        >
          <AuthWidget />
        </header>
        {children}
      </body>
    </html>
  );
}
