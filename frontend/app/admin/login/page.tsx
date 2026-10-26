"use client";

import React, { useState, FormEvent } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/lib/context/AuthContext";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Card,
  CardHeader,
  CardTitle,
  CardDescription,
  CardContent,
  CardFooter,
} from "@/components/ui/card";
import { AuroraText } from "@/components/ui/aurora";
import { ShineBorder } from "@/components/ui/shine_border";
import { AnimatedThemeToggler } from "@/components/ui/theme_toggler";
import { Eye, EyeOff, User, Lock, ShieldAlert, ShieldCheck } from "lucide-react";

// ── Single-admin credential check ──────────────────────────────────────
// NOTE: this is a client-side gate only, matching the pattern of the
// existing student/parent/teacher login. For anything beyond local/dev
// use, move this check to a real backend endpoint (e.g. POST /api/admin/login)
// that verifies against a hashed password server-side — a client-side
// env comparison can be read out of the shipped JS bundle.
const ADMIN_USERNAME = process.env.NEXT_PUBLIC_ADMIN_USERNAME || "admin";
const ADMIN_PASSWORD = process.env.NEXT_PUBLIC_ADMIN_PASSWORD || "admin312";

export default function AdminLoginPage() {
  const router = useRouter();
  const { login, user } = useAuth();

  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [error, setError] = useState("");
  const [isLoading, setIsLoading] = useState(false);

  React.useEffect(() => {
    if (user && (user as any).role === "Admin") {
      router.push("/admin");
    }
  }, [user, router]);

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError("");

    if (!username.trim() || !password) {
      setError("Please enter both username and password.");
      return;
    }

    setIsLoading(true);

    setTimeout(() => {
      try {
        if (!ADMIN_PASSWORD) {
          setError(
            "Admin password is not configured. Set NEXT_PUBLIC_ADMIN_PASSWORD."
          );
          setIsLoading(false);
          return;
        }

        if (
          username.trim() !== ADMIN_USERNAME ||
          password !== ADMIN_PASSWORD
        ) {
          setError("Invalid admin credentials.");
          setIsLoading(false);
          return;
        }

        // "Admin" must exist on the UserRole type in AuthContext.
        // If it doesn't yet, add it: type UserRole = "Student" | "Parent" | "Teacher" | "Admin";
        login(username.trim(), "Admin" as any);
        router.push("/admin");
      } catch (err) {
        setError("An unexpected error occurred during login. Please try again.");
        setIsLoading(false);
      }
    }, 500);
  };

  return (
    <div className="min-h-screen relative flex items-center justify-center p-4 bg-background overflow-hidden">
      <div className="absolute inset-0 pointer-events-none opacity-20 dark:opacity-40">
        <div className="absolute top-[-20%] left-[-20%] w-[60%] h-[60%] rounded-full bg-[radial-gradient(circle,rgba(124,156,255,0.25)_0%,transparent_70%)] animate-aurora"></div>
        <div className="absolute bottom-[-20%] right-[-20%] w-[60%] h-[60%] rounded-full bg-[radial-gradient(circle,rgba(62,207,142,0.18)_0%,transparent_70%)] animate-aurora"></div>
      </div>

      <div className="fixed top-6 right-6 z-50">
        <AnimatedThemeToggler className="p-2.5 rounded-full bg-input/20 border border-input/30 backdrop-blur-md hover:bg-input/40 transition-colors shadow-lg" />
      </div>

      <div className="w-full max-w-md relative z-10 transition-all duration-300">
        <div className="text-center mb-8">
          <h1 className="text-5xl font-extrabold tracking-tight select-none">
            V<AuroraText>BOT</AuroraText>
          </h1>
          <p className="text-muted-foreground mt-2 text-sm flex items-center justify-center gap-1.5">
            <ShieldCheck className="w-3.5 h-3.5" />
            Admin Console
          </p>
        </div>

        <Card className="relative overflow-hidden bg-card/45 backdrop-blur-xl border border-border/40 shadow-2xl p-2">
          <ShineBorder borderWidth={1.5} duration={12} />

          <CardHeader>
            <CardTitle className="text-2xl font-bold tracking-tight text-center">
              Admin Sign In
            </CardTitle>
            <CardDescription className="text-center">
              Restricted access — administrator credentials only
            </CardDescription>
          </CardHeader>

          <form onSubmit={handleSubmit}>
            <CardContent className="space-y-4 pt-2">
              {error && (
                <div className="flex items-center gap-2 p-3 rounded-lg bg-destructive/15 border border-destructive/30 text-destructive text-sm animate-shake">
                  <ShieldAlert className="w-4 h-4 flex-shrink-0" />
                  <span>{error}</span>
                </div>
              )}

              <div className="space-y-2">
                <label className="text-sm font-medium leading-none">
                  Username
                </label>
                <div className="relative">
                  <Input
                    type="text"
                    placeholder="Enter admin username"
                    value={username}
                    onChange={(e) => setUsername(e.target.value)}
                    className="pl-10 h-10 bg-input/10 border-input/40 backdrop-blur-sm focus-visible:ring-ring"
                    autoComplete="username"
                  />
                  <User className="absolute left-3.5 top-3 w-4 h-4 text-muted-foreground/75" />
                </div>
              </div>

              <div className="space-y-2">
                <label className="text-sm font-medium leading-none">
                  Password
                </label>
                <div className="relative">
                  <Input
                    type={showPassword ? "text" : "password"}
                    placeholder="••••••••"
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    className="pl-10 pr-10 h-10 bg-input/10 border-input/40 backdrop-blur-sm focus-visible:ring-ring"
                    autoComplete="current-password"
                  />
                  <Lock className="absolute left-3.5 top-3 w-4 h-4 text-muted-foreground/75" />
                  <button
                    type="button"
                    onClick={() => setShowPassword((prev) => !prev)}
                    className="absolute right-3 top-3.5 text-muted-foreground/75 hover:text-foreground transition-colors"
                  >
                    {showPassword ? (
                      <EyeOff className="w-4 h-4" />
                    ) : (
                      <Eye className="w-4 h-4" />
                    )}
                  </button>
                </div>
              </div>
            </CardContent>

            <CardFooter className="flex flex-col space-y-4 pt-4 pb-2">
              <Button
                type="submit"
                disabled={isLoading}
                className="w-full h-10 font-medium bg-foreground text-background hover:opacity-90 active:scale-[0.98] transition-all rounded-md shadow-lg"
              >
                {isLoading ? (
                  <span className="flex items-center justify-center gap-2">
                    <span className="w-4 h-4 border-2 border-background border-t-transparent rounded-full animate-spin"></span>
                    Verifying...
                  </span>
                ) : (
                  "Sign in"
                )}
              </Button>
              <p className="text-[11px] text-center text-muted-foreground/80 leading-normal">
                This console is for authorized administrators only.
              </p>
            </CardFooter>
          </form>
        </Card>
      </div>
    </div>
  );
}