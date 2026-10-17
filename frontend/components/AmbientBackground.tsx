/** The portfolio's ambient backdrop: slow-floating, heavily blurred colour pools behind the page. */
export default function AmbientBackground() {
  return (
    <div aria-hidden className="pointer-events-none fixed inset-0 z-0 overflow-hidden">
      <div
        className="absolute inset-0"
        style={{
          background: 'radial-gradient(ellipse at top, #0a0a0f 0%, #050506 50%, #020203 100%)',
        }}
      />
      <div
        className="absolute -top-[200px] left-1/2 h-[900px] w-[1400px] -translate-x-1/2 rounded-full opacity-[0.14]"
        style={{
          background: '#0ea5e9',
          filter: 'blur(150px)',
          animation: 'float 10s ease-in-out infinite',
        }}
      />
      <div
        className="absolute top-[10%] -left-[300px] h-[600px] w-[800px] rounded-full opacity-[0.08]"
        style={{
          background: 'linear-gradient(to bottom right, #7c3aed, #db2777)',
          filter: 'blur(120px)',
          animation: 'float-slow 8s ease-in-out infinite',
        }}
      />
      <div
        className="absolute top-[35%] -right-[200px] h-[500px] w-[700px] rounded-full opacity-[0.08]"
        style={{
          background: 'linear-gradient(to bottom left, #0ea5e9, #2563eb)',
          filter: 'blur(100px)',
          animation: 'float 12s ease-in-out infinite reverse',
        }}
      />
    </div>
  )
}
