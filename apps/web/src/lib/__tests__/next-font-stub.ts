// Vitest stand-in for next/font/google, which only works inside Next's compiler.
// Every font loader returns the same shape Next does (className, style.fontFamily, variable).
const loader = () => ({ className: "", style: { fontFamily: "serif" }, variable: "" });

export const Dancing_Script = loader;
export const Geist = loader;
export const Inter = loader;
export const JetBrains_Mono = loader;
