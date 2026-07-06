export default function Placeholder({ title, sub }: { title: string; sub: string }) {
  return (
    <div className="page">
      <div className="placeholder">
        <div className="mark" />
        <div className="big">{title}</div>
        <div>{sub}</div>
        <div className="dim" style={{ fontSize: 12, marginTop: 6 }}>
          Coming next in this build.
        </div>
      </div>
    </div>
  )
}
