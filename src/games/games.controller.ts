import {
  Controller,
  Post,
  Get,
  Param,
  Body,
  ParseIntPipe,
  HttpCode,
  HttpStatus,
} from '@nestjs/common';
import { GamesService } from './games.service';
import { SaveGameDto } from './dto/save-game.dto';

@Controller('api/v1')
export class GamesController {
  constructor(private readonly gamesService: GamesService) {}

  /**
   * POST /api/v1/save-game
   * lol-custom-exe 에서 게임 종료 후 결과 JSON을 전송
   * Body: { gameId: number, report: object }
   */
  @Post('save-game')
  @HttpCode(HttpStatus.CREATED)
  async saveGame(@Body() dto: SaveGameDto) {
    return this.gamesService.createGame(dto);
  }

  /**
   * GET /api/v1/game/:gameId
   * gameId 로 Firestore에 저장된 게임 결과 조회
   */
  @Get('game/:gameId')
  async getGame(@Param('gameId', ParseIntPipe) gameId: number) {
    return this.gamesService.readGame(gameId);
  }
}
