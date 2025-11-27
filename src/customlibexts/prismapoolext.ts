import { PrismaClient } from '../../generated/prisma';

const globalForPrisma = globalThis as unknown as {
  pooledPrisma?: PrismaClient;
};

export const pooledPrisma =
  globalForPrisma.pooledPrisma ??
  new PrismaClient();

if (!globalForPrisma.pooledPrisma) {
  globalForPrisma.pooledPrisma = pooledPrisma;
}
