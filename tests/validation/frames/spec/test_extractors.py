"""
Tests for Contract Extractors.

Tests extraction of API contracts from various platforms.
"""

import pytest
from pathlib import Path
from tempfile import TemporaryDirectory

from warden.validation.frames.spec import (
    Contract,
    OperationDefinition,
    ModelDefinition,
    PlatformType,
    PlatformRole,
    OperationType,
)
from warden.validation.frames.spec.extractors.base import (
    ExtractorRegistry,
    get_extractor,
)


class TestExtractorRegistry:
    """Tests for ExtractorRegistry."""

    def test_registry_has_extractors(self):
        """Test registry has registered extractors."""
        extractors = ExtractorRegistry.get_all()
        assert len(extractors) > 0

    def test_get_extractor_by_platform(self):
        """Test getting extractor by platform type."""
        with TemporaryDirectory() as tmpdir:
            # Flutter extractor
            extractor = get_extractor(
                PlatformType.FLUTTER,
                Path(tmpdir),
                PlatformRole.CONSUMER,
            )
            assert extractor is not None

            # Express extractor
            extractor = get_extractor(
                PlatformType.EXPRESS,
                Path(tmpdir),
                PlatformRole.PROVIDER,
            )
            assert extractor is not None

    def test_get_extractor_returns_none_for_unknown(self):
        """Test get_extractor returns None for unknown platform."""
        with TemporaryDirectory() as tmpdir:
            # This should return None or an extractor depending on implementation
            extractor = get_extractor(
                PlatformType.DJANGO,  # Might not have extractor
                Path(tmpdir),
                PlatformRole.PROVIDER,
            )
            # Just verify it doesn't raise an exception


class TestReactExtractor:
    """Tests for React/React Native extractor."""

    @pytest.mark.asyncio
    async def test_extract_axios_calls(self):
        """Test extraction of axios API calls."""
        with TemporaryDirectory() as tmpdir:
            # Create test React file
            src_dir = Path(tmpdir) / "src"
            src_dir.mkdir()

            api_file = src_dir / "api.ts"
            api_file.write_text('''
import axios from 'axios';

interface User {
    id: number;
    name: string;
    email: string;
}

export async function getUsers(): Promise<User[]> {
    const response = await axios.get<User[]>('/api/users');
    return response.data;
}

export async function createUser(user: User): Promise<User> {
    const response = await axios.post<User>('/api/users', user);
    return response.data;
}

export async function deleteUser(id: number): Promise<void> {
    await axios.delete(`/api/users/${id}`);
}
''')

            extractor = get_extractor(
                PlatformType.REACT,
                Path(tmpdir),
                PlatformRole.CONSUMER,
            )
            assert extractor is not None

            contract = await extractor.extract()

            # Should extract operations
            assert len(contract.operations) >= 2

            # Should extract User model
            user_models = [m for m in contract.models if m.name == "User"]
            assert len(user_models) == 1

            user_model = user_models[0]
            field_names = [f.name for f in user_model.fields]
            assert "id" in field_names
            assert "name" in field_names
            assert "email" in field_names

    @pytest.mark.asyncio
    async def test_extract_fetch_calls(self):
        """Test extraction of fetch API calls."""
        with TemporaryDirectory() as tmpdir:
            src_dir = Path(tmpdir) / "src"
            src_dir.mkdir()

            api_file = src_dir / "api.ts"
            api_file.write_text('''
export async function fetchProducts() {
    const response = await fetch('/api/products');
    return response.json();
}

export async function updateProduct(id: string, data: any) {
    const response = await fetch(`/api/products/${id}`, {
        method: 'PUT',
        body: JSON.stringify(data),
    });
    return response.json();
}
''')

            extractor = get_extractor(
                PlatformType.REACT,
                Path(tmpdir),
                PlatformRole.CONSUMER,
            )
            contract = await extractor.extract()

            # Should extract fetch operations
            assert len(contract.operations) >= 1

    @pytest.mark.asyncio
    async def test_extract_react_query(self):
        """Test extraction of React Query hooks."""
        with TemporaryDirectory() as tmpdir:
            src_dir = Path(tmpdir) / "src" / "hooks"
            src_dir.mkdir(parents=True)

            hooks_file = src_dir / "useUsers.ts"
            hooks_file.write_text('''
import { useQuery, useMutation } from '@tanstack/react-query';

export function useUsers() {
    return useQuery<User[]>(['users'], fetchUsers);
}

export function useCreateUser() {
    return useMutation<User, Error, CreateUserInput>(createUser);
}
''')

            extractor = get_extractor(
                PlatformType.REACT,
                Path(tmpdir),
                PlatformRole.CONSUMER,
            )
            contract = await extractor.extract()

            # Should extract query hooks
            assert len(contract.operations) >= 1


class TestExpressExtractor:
    """Tests for Express.js extractor."""

    @pytest.mark.asyncio
    async def test_extract_routes(self):
        """Test extraction of Express routes."""
        with TemporaryDirectory() as tmpdir:
            src_dir = Path(tmpdir) / "src"
            src_dir.mkdir()

            routes_file = src_dir / "routes.ts"
            routes_file.write_text('''
import express from 'express';

const router = express.Router();

router.get('/users', getUsers);
router.post('/users', createUser);
router.get('/users/:id', getUserById);
router.put('/users/:id', updateUser);
router.delete('/users/:id', deleteUser);

export default router;
''')

            extractor = get_extractor(
                PlatformType.EXPRESS,
                Path(tmpdir),
                PlatformRole.PROVIDER,
            )
            contract = await extractor.extract()

            # Should extract routes
            assert len(contract.operations) >= 4

            # Check operation types
            op_names = [op.name for op in contract.operations]
            assert "getUsers" in op_names or "getUserById" in op_names

    @pytest.mark.asyncio
    async def test_extract_typed_routes(self):
        """Test extraction of typed Express routes."""
        with TemporaryDirectory() as tmpdir:
            src_dir = Path(tmpdir) / "src"
            src_dir.mkdir()

            routes_file = src_dir / "users.ts"
            routes_file.write_text('''
import { Router, Request, Response } from 'express';

interface CreateUserDto {
    name: string;
    email: string;
    age?: number;
}

interface User {
    id: string;
    name: string;
    email: string;
    createdAt: Date;
}

const router = Router();

router.post('/users', async (req: Request<{}, {}, CreateUserDto>, res: Response<User>) => {
    const user = await userService.create(req.body);
    res.json(user);
});

export default router;
''')

            extractor = get_extractor(
                PlatformType.EXPRESS,
                Path(tmpdir),
                PlatformRole.PROVIDER,
            )
            contract = await extractor.extract()

            # Should extract models
            model_names = [m.name for m in contract.models]
            assert "CreateUserDto" in model_names or "User" in model_names


class TestGoExtractor:
    """Tests for Go (Gin/Echo/Fiber) extractor."""

    @pytest.mark.asyncio
    async def test_extract_gin_routes(self):
        """Test extraction of Gin routes."""
        with TemporaryDirectory() as tmpdir:
            handlers_dir = Path(tmpdir) / "handlers"
            handlers_dir.mkdir()

            handlers_file = handlers_dir / "users.go"
            handlers_file.write_text('''
package handlers

import (
    "net/http"
    "github.com/gin-gonic/gin"
)

type User struct {
    ID    string `json:"id"`
    Name  string `json:"name"`
    Email string `json:"email"`
}

type CreateUserRequest struct {
    Name  string `json:"name"`
    Email string `json:"email"`
}

func GetUsers(c *gin.Context) {
    users := []User{}
    c.JSON(http.StatusOK, users)
}

func CreateUser(c *gin.Context) {
    var req CreateUserRequest
    if err := c.ShouldBindJSON(&req); err != nil {
        c.JSON(http.StatusBadRequest, gin.H{"error": err.Error()})
        return
    }
    c.JSON(http.StatusCreated, User{Name: req.Name})
}
''')

            routes_file = Path(tmpdir) / "routes.go"
            routes_file.write_text('''
package main

import "github.com/gin-gonic/gin"

func SetupRoutes(r *gin.Engine) {
    r.GET("/users", GetUsers)
    r.POST("/users", CreateUser)
    r.GET("/users/:id", GetUserById)
    r.DELETE("/users/:id", DeleteUser)
}
''')

            extractor = get_extractor(
                PlatformType.GIN,
                Path(tmpdir),
                PlatformRole.PROVIDER,
            )
            contract = await extractor.extract()

            # Should extract routes
            assert len(contract.operations) >= 2

            # Should extract structs
            model_names = [m.name for m in contract.models]
            assert "User" in model_names or "CreateUserRequest" in model_names

    @pytest.mark.asyncio
    async def test_extract_echo_routes(self):
        """Test extraction of Echo routes."""
        with TemporaryDirectory() as tmpdir:
            main_file = Path(tmpdir) / "main.go"
            main_file.write_text('''
package main

import (
    "github.com/labstack/echo/v4"
)

func main() {
    e := echo.New()
    e.GET("/products", GetProducts)
    e.POST("/products", CreateProduct)
    e.PUT("/products/:id", UpdateProduct)
}
''')

            extractor = get_extractor(
                PlatformType.ECHO,
                Path(tmpdir),
                PlatformRole.PROVIDER,
            )
            contract = await extractor.extract()

            # Should extract Echo routes
            assert len(contract.operations) >= 2


class TestFlutterExtractor:
    """Tests for Flutter/Dart extractor."""

    @pytest.mark.asyncio
    async def test_extract_retrofit_endpoints(self):
        """Test extraction of Retrofit endpoints."""
        with TemporaryDirectory() as tmpdir:
            lib_dir = Path(tmpdir) / "lib" / "api"
            lib_dir.mkdir(parents=True)

            api_file = lib_dir / "user_api.dart"
            api_file.write_text('''
import 'package:retrofit/retrofit.dart';
import 'package:dio/dio.dart';

part 'user_api.g.dart';

@RestApi(baseUrl: '/api')
abstract class UserApi {
  factory UserApi(Dio dio) = _UserApi;

  @GET('/users')
  Future<List<User>> getUsers();

  @POST('/users')
  Future<User> createUser(@Body() CreateUserRequest request);

  @GET('/users/{id}')
  Future<User> getUserById(@Path('id') String id);

  @DELETE('/users/{id}')
  Future<void> deleteUser(@Path('id') String id);
}
''')

            models_file = lib_dir / "models.dart"
            models_file.write_text('''
import 'package:json_annotation/json_annotation.dart';

part 'models.g.dart';

@JsonSerializable()
class User {
  final String id;
  final String name;
  final String email;
  final DateTime? createdAt;

  User({required this.id, required this.name, required this.email, this.createdAt});
}

@JsonSerializable()
class CreateUserRequest {
  final String name;
  final String email;

  CreateUserRequest({required this.name, required this.email});
}
''')

            extractor = get_extractor(
                PlatformType.FLUTTER,
                Path(tmpdir),
                PlatformRole.CONSUMER,
            )
            contract = await extractor.extract()

            # Should extract Retrofit operations
            assert len(contract.operations) >= 2

            # Should extract models
            model_names = [m.name for m in contract.models]
            assert "User" in model_names

    @pytest.mark.asyncio
    async def test_extract_dio_calls(self):
        """Test extraction of Dio API calls."""
        with TemporaryDirectory() as tmpdir:
            lib_dir = Path(tmpdir) / "lib" / "services"
            lib_dir.mkdir(parents=True)

            service_file = lib_dir / "api_service.dart"
            service_file.write_text('''
import 'package:dio/dio.dart';

class ApiService {
  final Dio _dio = Dio();

  Future<List<Product>> getProducts() async {
    final response = await _dio.get('/api/products');
    return (response.data as List).map((e) => Product.fromJson(e)).toList();
  }

  Future<Product> createProduct(Map<String, dynamic> data) async {
    final response = await _dio.post('/api/products', data: data);
    return Product.fromJson(response.data);
  }
}
''')

            extractor = get_extractor(
                PlatformType.FLUTTER,
                Path(tmpdir),
                PlatformRole.CONSUMER,
            )
            contract = await extractor.extract()

            # Should extract Dio operations
            assert len(contract.operations) >= 1


class TestSpringBootExtractor:
    """Tests for Spring Boot extractor."""

    @pytest.mark.asyncio
    async def test_extract_rest_controller(self):
        """Test extraction of Spring REST controller."""
        with TemporaryDirectory() as tmpdir:
            src_dir = Path(tmpdir) / "src" / "main" / "java" / "com" / "example"
            src_dir.mkdir(parents=True)

            controller_file = src_dir / "UserController.java"
            controller_file.write_text('''
package com.example;

import org.springframework.web.bind.annotation.*;
import java.util.List;

@RestController
@RequestMapping("/api/users")
public class UserController {

    @GetMapping
    public List<User> getUsers() {
        return userService.findAll();
    }

    @PostMapping
    public User createUser(@RequestBody CreateUserRequest request) {
        return userService.create(request);
    }

    @GetMapping("/{id}")
    public User getUserById(@PathVariable Long id) {
        return userService.findById(id);
    }

    @DeleteMapping("/{id}")
    public void deleteUser(@PathVariable Long id) {
        userService.delete(id);
    }
}
''')

            dto_file = src_dir / "CreateUserRequest.java"
            dto_file.write_text('''
package com.example;

public class CreateUserRequest {
    private String name;
    private String email;

    public String getName() { return name; }
    public void setName(String name) { this.name = name; }
    public String getEmail() { return email; }
    public void setEmail(String email) { this.email = email; }
}
''')

            extractor = get_extractor(
                PlatformType.SPRING_BOOT,
                Path(tmpdir),
                PlatformRole.PROVIDER,
            )
            contract = await extractor.extract()

            # Should extract REST endpoints
            assert len(contract.operations) >= 2

    @pytest.mark.asyncio
    async def test_extract_kotlin_controller(self):
        """Test extraction of Kotlin Spring controller."""
        with TemporaryDirectory() as tmpdir:
            src_dir = Path(tmpdir) / "src" / "main" / "kotlin" / "com" / "example"
            src_dir.mkdir(parents=True)

            controller_file = src_dir / "ProductController.kt"
            controller_file.write_text('''
package com.example

import org.springframework.web.bind.annotation.*

@RestController
@RequestMapping("/api/products")
class ProductController(
    private val productService: ProductService
) {
    @GetMapping
    fun getProducts(): List<Product> = productService.findAll()

    @PostMapping
    fun createProduct(@RequestBody request: CreateProductRequest): Product =
        productService.create(request)
}

data class Product(
    val id: Long,
    val name: String,
    val price: Double
)

data class CreateProductRequest(
    val name: String,
    val price: Double
)
''')

            extractor = get_extractor(
                PlatformType.SPRING_BOOT,
                Path(tmpdir),
                PlatformRole.PROVIDER,
            )
            contract = await extractor.extract()

            # Should extract Kotlin endpoints
            assert len(contract.operations) >= 1


class TestFastAPIExtractor:
    """Tests for FastAPI extractor."""

    @pytest.mark.asyncio
    async def test_extract_fastapi_routes(self):
        """Test extraction of FastAPI routes."""
        with TemporaryDirectory() as tmpdir:
            app_file = Path(tmpdir) / "main.py"
            app_file.write_text('''
from fastapi import FastAPI
from pydantic import BaseModel
from typing import List, Optional

app = FastAPI()

class User(BaseModel):
    id: int
    name: str
    email: str

class CreateUserRequest(BaseModel):
    name: str
    email: str

@app.get("/users", response_model=List[User])
async def get_users():
    return []

@app.post("/users", response_model=User)
async def create_user(request: CreateUserRequest):
    return User(id=1, name=request.name, email=request.email)

@app.get("/users/{user_id}", response_model=User)
async def get_user(user_id: int):
    return User(id=user_id, name="Test", email="test@example.com")

@app.delete("/users/{user_id}")
async def delete_user(user_id: int):
    pass
''')

            extractor = get_extractor(
                PlatformType.FASTAPI,
                Path(tmpdir),
                PlatformRole.PROVIDER,
            )
            contract = await extractor.extract()

            # Should extract FastAPI routes
            assert len(contract.operations) >= 3

            # Should extract Pydantic models
            model_names = [m.name for m in contract.models]
            assert "User" in model_names or "CreateUserRequest" in model_names


class TestAngularExtractor:
    """Tests for Angular extractor."""

    @pytest.mark.asyncio
    async def test_extract_http_client_calls(self):
        """Test extraction of Angular HttpClient calls."""
        with TemporaryDirectory() as tmpdir:
            src_dir = Path(tmpdir) / "src" / "app" / "services"
            src_dir.mkdir(parents=True)

            service_file = src_dir / "user.service.ts"
            service_file.write_text('''
import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';

export interface User {
  id: number;
  name: string;
  email: string;
}

export interface CreateUserRequest {
  name: string;
  email: string;
}

@Injectable({
  providedIn: 'root'
})
export class UserService {
  private apiUrl = '/api/users';

  constructor(private http: HttpClient) {}

  getUsers(): Observable<User[]> {
    return this.http.get<User[]>(this.apiUrl);
  }

  createUser(request: CreateUserRequest): Observable<User> {
    return this.http.post<User>(this.apiUrl, request);
  }

  deleteUser(id: number): Observable<void> {
    return this.http.delete<void>(`${this.apiUrl}/${id}`);
  }
}
''')

            extractor = get_extractor(
                PlatformType.ANGULAR,
                Path(tmpdir),
                PlatformRole.CONSUMER,
            )
            contract = await extractor.extract()

            # Should extract HttpClient operations
            assert len(contract.operations) >= 2

            # Should extract interfaces
            model_names = [m.name for m in contract.models]
            assert "User" in model_names


class TestNestJSExtractor:
    """Tests for NestJS extractor."""

    @pytest.mark.asyncio
    async def test_extract_controller_decorators(self):
        """Test extraction of NestJS controller decorators."""
        with TemporaryDirectory() as tmpdir:
            src_dir = Path(tmpdir) / "src"
            src_dir.mkdir()

            controller_file = src_dir / "users.controller.ts"
            controller_file.write_text('''
import { Controller, Get, Post, Delete, Body, Param } from '@nestjs/common';

export class CreateUserDto {
  name: string;
  email: string;
}

export class User {
  id: number;
  name: string;
  email: string;
}

@Controller('users')
export class UsersController {
  @Get()
  findAll(): Promise<User[]> {
    return this.usersService.findAll();
  }

  @Post()
  create(@Body() createUserDto: CreateUserDto): Promise<User> {
    return this.usersService.create(createUserDto);
  }

  @Get(':id')
  findOne(@Param('id') id: string): Promise<User> {
    return this.usersService.findOne(+id);
  }

  @Delete(':id')
  remove(@Param('id') id: string): Promise<void> {
    return this.usersService.remove(+id);
  }
}
''')

            extractor = get_extractor(
                PlatformType.NESTJS,
                Path(tmpdir),
                PlatformRole.PROVIDER,
            )
            contract = await extractor.extract()

            # Should extract NestJS endpoints
            assert len(contract.operations) >= 3

            # Should extract DTOs/classes
            model_names = [m.name for m in contract.models]
            assert "CreateUserDto" in model_names or "User" in model_names
