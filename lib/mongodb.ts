// import { MongoClient } from 'mongodb';

const MONGODB_URI="mongodb+srv://nilamathi312_db_user:ju5tyUjrkguENUbM@chathistory.me7mbcu.mongodb.net/"
const MONGODB_DB="chat_history_db"

// if (!MONGODB_URI) {
//   throw new Error('Please define the MONGODB_URI environment variable');
// }

// if (!MONGODB_DB) {
//   throw new Error('Please define the MONGODB_DB environment variable');
// }

// const uri = MONGODB_URI;

// let client: MongoClient;
// let clientPromise: Promise<MongoClient>;

// // In development, we use a global variable to maintain the connection
// // This prevents creating new connections during hot reloads
// if (process.env.NODE_ENV === 'development') {
//   const globalWithMongo = global as typeof global & {
//     _mongoClientPromise?: Promise<MongoClient>;
//   };

//   if (!globalWithMongo._mongoClientPromise) {
//     client = new MongoClient(uri);
//     globalWithMongo._mongoClientPromise = client.connect();
//   }
//   clientPromise = globalWithMongo._mongoClientPromise;
// } else {
//   // In production, create a new connection for each instance
//   client = new MongoClient(uri);
//   clientPromise = client.connect();
// }

import mongoose from "mongoose"



if (!MONGODB_URI) {
  throw new Error("Please define MONGODB_URI")
}

let cached = (global as any).mongoose || { conn: null, promise: null }

export async function connectDB() {
  if (cached.conn) return cached.conn

  if (!cached.promise) {
    cached.promise = mongoose.connect(MONGODB_URI).then((mongoose) => mongoose)
  }

  cached.conn = await cached.promise
  return cached.conn
}