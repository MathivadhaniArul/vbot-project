"use client";

import React, { createContext, useContext, useState, useEffect } from "react";

export type UserRole = "Student" | "Parent" | "Teacher";

interface UserSession {
  username: string;
  role: UserRole;
}

interface AuthContextType {
  user: UserSession | null;
  loading: boolean;
  login: (username: string, role: UserRole) => void;
  logout: () => void;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

export const AuthProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [user, setUser] = useState<UserSession | null>(null);
  const [loading, setLoading] = useState(true);

  // Load session from localStorage on mount
  useEffect(() => {
    try {
      const storedUser = localStorage.getItem("vbot_user");
      const storedRole = localStorage.getItem("vbot_role");
      if (storedUser && storedRole) {
        setUser({
          username: storedUser,
          role: storedRole as UserRole,
        });
      }
    } catch (err) {
      console.error("Failed to load auth session:", err);
    } finally {
      setLoading(false);
    }
  }, []);

  const login = (username: string, role: UserRole) => {
    setUser({ username, role });
    try {
      localStorage.setItem("vbot_user", username);
      localStorage.setItem("vbot_role", role);
    } catch (err) {
      console.error("Failed to save auth session:", err);
    }
  };

  const logout = () => {
    setUser(null);
    try {
      localStorage.removeItem("vbot_user");
      localStorage.removeItem("vbot_role");
    } catch (err) {
      console.error("Failed to clear auth session:", err);
    }
  };

  return (
    <AuthContext.Provider value={{ user, loading, login, logout }}>
      {children}
    </AuthContext.Provider>
  );
};

export const useAuth = () => {
  const context = useContext(AuthContext);
  if (context === undefined) {
    throw new Error("useAuth must be used within an AuthProvider");
  }
  return context;
};
