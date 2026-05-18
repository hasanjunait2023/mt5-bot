interface Props {
  pipsToSl: number
  pipsToTp: number
}

export function PriceBar({ pipsToSl, pipsToTp }: Props) {
  const total = Math.abs(pipsToSl) + Math.abs(pipsToTp) || 1
  const tpPct = Math.min(100, (Math.abs(pipsToTp) / total) * 100)
  const slPct = Math.min(100, (Math.abs(pipsToSl) / total) * 100)

  return (
    <div className="flex items-center gap-1 min-w-[80px]">
      <span className="text-loss text-xs font-mono w-8 text-right">{Math.abs(pipsToSl).toFixed(1)}</span>
      <div className="flex-1 h-1 bg-bg-overlay rounded-full overflow-hidden">
        <div className="flex h-full">
          <div className="bg-loss h-full" style={{ width: `${slPct}%` }} />
          <div className="bg-profit h-full" style={{ width: `${tpPct}%` }} />
        </div>
      </div>
      <span className="text-profit text-xs font-mono w-8">{Math.abs(pipsToTp).toFixed(1)}</span>
    </div>
  )
}
