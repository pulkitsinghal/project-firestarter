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
      <body>{children}</body>
    </html>
  );
}
