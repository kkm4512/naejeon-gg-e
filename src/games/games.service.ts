import {
  Injectable,
  ConflictException,
  NotFoundException,
  Logger,
} from '@nestjs/common';
import { FirebaseService } from '../firebase/firebase.service';
import { SaveGameDto } from './dto/save-game.dto';

@Injectable()
export class GamesService {
  private readonly logger = new Logger(GamesService.name);

  constructor(private readonly firebase: FirebaseService) {}

  private get collection(): string {
    return process.env.FIRESTORE_COLLECTION ?? 'custom_games';
  }

  /** CREATE: 게임 결과를 Firestore에 저장 */
  async createGame(dto: SaveGameDto): Promise<{ id: string }> {
    const { gameId, report } = dto;
    const docRef = this.firebase.db.collection(this.collection).doc(String(gameId));
    const existing = await docRef.get();

    if (existing.exists) {
      throw new ConflictException(`gameId ${gameId} 는 이미 등록된 전적입니다.`);
    }

    await docRef.set({
      gameId,
      report,
      createdAt: new Date().toISOString(),
    });

    this.logger.log(`Game saved: ${gameId}`);
    return { id: String(gameId) };
  }

  /** READ: gameId로 Firestore에서 게임 결과 조회 */
  async readGame(gameId: number): Promise<Record<string, any>> {
    const docRef = this.firebase.db.collection(this.collection).doc(String(gameId));
    const doc = await docRef.get();

    if (!doc.exists) {
      throw new NotFoundException(`gameId ${gameId} 를 찾을 수 없습니다.`);
    }

    return doc.data() as Record<string, any>;
  }
}
