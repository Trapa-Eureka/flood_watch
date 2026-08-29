import Link from "next/link";
import MapView from "./_components/MapView";

export default function Home() {
  return (
    <>
      <MapView />
      <nav style={{ position: "fixed", top: 12, left: 12, zIndex: 10, display: "flex", gap: 8 }}>
        <Link
          href="/events"
          style={{ background: "#fff", padding: "8px 14px", borderRadius: 6, boxShadow: "0 1px 4px rgba(0,0,0,0.2)", textDecoration: "none", color: "#111", fontSize: 14, fontWeight: 600 }}
        >
          이벤트 보기
        </Link>
        <Link
          href="/admin"
          style={{ background: "#fff", padding: "8px 14px", borderRadius: 6, boxShadow: "0 1px 4px rgba(0,0,0,0.2)", textDecoration: "none", color: "#111", fontSize: 14, fontWeight: 600 }}
        >
          관리자
        </Link>
      </nav>
    </>
  );
}
