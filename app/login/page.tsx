"use client";

import React, { useState, FormEvent } from "react";
import { useRouter } from "next/navigation";
import { useAuth, UserRole } from "@/lib/context/AuthContext";
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
import {
  Select,
  SelectTrigger,
  SelectValue,
  SelectContent,
  SelectItem,
} from "@/components/ui/select";
import { AuroraText } from "@/components/ui/aurora";
import { ShineBorder } from "@/components/ui/shine_border";
import { AnimatedThemeToggler } from "@/components/ui/theme_toggler";
import { Eye, EyeOff, User, Lock, ShieldAlert } from "lucide-react";

export default function LoginPage() {
  const router = useRouter();
  const { login, user } = useAuth();

  const [role, setRole] = useState<UserRole | "">("");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [error, setError] = useState("");
  const [isLoading, setIsLoading] = useState(false);

  // If already authenticated, redirect to chat immediately
  React.useEffect(() => {
    if (user) {
      router.push("/");
    }
  }, [user, router]);

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError("");

    if (!role) {
      setError("Please select a role (Student, Parent, or Teacher).");
      return;
    }
    if (!username.trim()) {
      setError("Please enter your username.");
      return;
    }
    if (!password) {
      setError("Please enter your password.");
      return;
    }
    if (password.length < 4) {
      setError("Password must be at least 4 characters long.");
      return;
    }

    setIsLoading(true);

    // Simulate standard frontend authentication delay for modern aesthetics
    setTimeout(() => {
      try {
        login(username.trim(), role as UserRole);
        router.push("/");
      } catch (err) {
        setError("An unexpected error occurred during login. Please try again.");
      } finally {
        setIsLoading(false);
      }
    }, 800);
  };

  return (
    <div className="min-h-screen relative flex items-center justify-center p-4 bg-background overflow-hidden">
      {/* Background ambient auroras */}
      <div className="absolute inset-0 pointer-events-none opacity-20 dark:opacity-40">
        <div className="absolute top-[-20%] left-[-20%] w-[60%] h-[60%] rounded-full bg-[radial-gradient(circle,rgba(255,0,128,0.25)_0%,transparent_70%)] animate-aurora"></div>
        <div className="absolute bottom-[-20%] right-[-20%] w-[60%] h-[60%] rounded-full bg-[radial-gradient(circle,rgba(0,112,243,0.25)_0%,transparent_70%)] animate-aurora"></div>
      </div>

      {/* Floating Theme Toggler */}
      <div className="fixed top-6 right-6 z-50">
        <AnimatedThemeToggler className="p-2.5 rounded-full bg-input/20 border border-input/30 backdrop-blur-md hover:bg-input/40 transition-colors shadow-lg" />
      </div>

      <div className="w-full max-w-md relative z-10 transition-all duration-300">
        {/* VBOT Header */}
        <div className="text-center mb-8">
          <h1 className="text-5xl font-extrabold tracking-tight select-none">
            V<AuroraText>BOT</AuroraText>
          </h1>
          <p className="text-muted-foreground mt-2 text-sm">
            VIT Regulations Assistant & Information Portal
          </p>
        </div>

        {/* Login Card */}
        <Card className="relative overflow-hidden bg-card/45 backdrop-blur-xl border border-border/40 shadow-2xl p-2">
          {/* Neon border animation */}
          <ShineBorder borderWidth={1.5} duration={12} />

          <CardHeader>
            <CardTitle className="text-2xl font-bold tracking-tight text-center">
              Welcome Back
            </CardTitle>
            <CardDescription className="text-center">
              Select your role and enter credentials to continue
            </CardDescription>
          </CardHeader>

          <form onSubmit={handleSubmit}>
            <CardContent className="space-y-4 pt-2">
              {/* Error Alert */}
              {error && (
                <div className="flex items-center gap-2 p-3 rounded-lg bg-destructive/15 border border-destructive/30 text-destructive text-sm animate-shake">
                  <ShieldAlert className="w-4 h-4 flex-shrink-0" />
                  <span>{error}</span>
                </div>
              )}

              {/* Role Selection */}
              <div className="space-y-2">
                <label className="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70">
                  Role
                </label>
                <Select value={role} onValueChange={(val) => setRole(val as UserRole)}>
                  <SelectTrigger className="w-full h-10 px-3 py-2 bg-input/10 border-input/40 rounded-md backdrop-blur-sm focus:ring-ring">
                    <SelectValue placeholder="Choose your role" />
                  </SelectTrigger>
                  <SelectContent className="bg-popover/95 backdrop-blur-md border border-border/40">
                    <SelectItem value="Student">Student</SelectItem>
                    <SelectItem value="Parent">Parent</SelectItem>
                    <SelectItem value="Teacher">Teacher</SelectItem>
                  </SelectContent>
                </Select>
              </div>

              {/* Username Input */}
              <div className="space-y-2">
                <label className="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70">
                  Username
                </label>
                <div className="relative">
                  <Input
                    type="text"
                    placeholder="Enter your username"
                    value={username}
                    onChange={(e) => setUsername(e.target.value)}
                    className="pl-10 h-10 bg-input/10 border-input/40 backdrop-blur-sm focus-visible:ring-ring"
                  />
                  <User className="absolute left-3.5 top-3 w-4 h-4 text-muted-foreground/75" />
                </div>
              </div>

              {/* Password Input */}
              <div className="space-y-2">
                <div className="flex justify-between items-center">
                  <label className="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70">
                    Password
                  </label>
                </div>
                <div className="relative">
                  <Input
                    type={showPassword ? "text" : "password"}
                    placeholder="••••••••"
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    className="pl-10 pr-10 h-10 bg-input/10 border-input/40 backdrop-blur-sm focus-visible:ring-ring"
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
                className="w-full h-10 font-medium bg-foreground text-background dark:bg-foreground dark:text-background hover:opacity-90 active:scale-[0.98] transition-all rounded-md shadow-lg"
              >
                {isLoading ? (
                  <span className="flex items-center justify-center gap-2">
                    <span className="w-4 h-4 border-2 border-background border-t-transparent rounded-full animate-spin"></span>
                    Authenticating...
                  </span>
                ) : (
                  "Login"
                )}
              </Button>
              <p className="text-[11px] text-center text-muted-foreground/80 leading-normal">
                Any username and 4+ character password are accepted for login.
              </p>
            </CardFooter>
          </form>
        </Card>
      </div>
    </div>
  );
}
